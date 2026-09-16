#works out which saved file came from which page of a comic, by walking the comic without downloading
#anything and lining that walk up against what is already on disk. the walk is the slow part and its
#result is cached; the alignment is what everything about chapters is later built on. #V 1.0

import argparse
import hashlib
import json
import os
import re
import html.parser
import shutil
import subprocess
import sys
from urllib.parse import urljoin
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

metadata_file = "mirror_metadata.json"
page_types = re.compile(r'\.(png|jpe?g|gif|webp|bmp)$', re.I)
#the number this script gave a page when it saved it: 0742_something.jpg, or a plain 0742.jpg
numbered = re.compile(r'^(\d+)(?:[._])')


def config_folder():
    return os.environ.get("MIRROR_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config")


def page_key(name):
    #two spellings of one page have to agree: the prefix this script adds is dropped, and an extension
    #appended twice is collapsed. a number followed by a dot is left alone - for a comic whose pages are
    #named 0005.gif that number is the page's whole identity.
    stem = re.sub(r'^\d{3,}_', '', name)
    stem = re.sub(r'\.(png|jpe?g|gif|webp)\.(png|jpe?g|gif|webp)$', r'.\1', stem, flags=re.I)
    return stem.lower()


def page_number(name):
    found = numbered.match(name)
    return int(found.group(1)) if found else None


def sort_key(name):
    #numbers sort as numbers, so 9 comes before 10 for a comic whose files were never padded
    return [int(bit) if bit.isdigit() else bit.lower() for bit in re.split(r'(\d+)', name)]


def folder_pages(folder):
    names = [f for f in os.listdir(folder)
             if page_types.search(f) and os.path.isfile(os.path.join(folder, f))]
    #the order the comic reads in: by the number this script saved it under where there is one, and by
    #name otherwise. the number is the order pages were fetched, which is the order they were published.
    if names and all(page_number(name) is not None for name in names):
        return sorted(names, key=lambda name: (page_number(name), sort_key(name)))
    return sorted(names, key=sort_key)


def index_path(folder, root=None, args=None):
    #the comic's own folder decides the name, and nothing else: passing a library folder or not must never
    #change which cache a comic uses. the short tag is what keeps two comics called Extras apart.
    if args is not None and getattr(args, "cache", None):
        return args.cache
    full = os.path.abspath(folder)
    tag = hashlib.sha1(full.replace(os.sep, '/').lower().encode('utf-8')).hexdigest()[:8]
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(full)).strip('_') or "comic"
    here = os.path.join(config_folder(), "index", "{0}.{1}.jsonl".format(name, tag))
    if os.path.exists(here):
        return here
    #the same comic reached by another path - a share on one machine, a mount inside a container - hashes
    #differently, so the comic itself says which cache is its own and that is used when it is there
    named = ((read_metadata(folder).get("history") or {}).get("index_cache"))
    if named:
        elsewhere = os.path.join(config_folder(), "index", named)
        if os.path.exists(elsewhere):
            return elsewhere
    return here


def read_index(path):
    pages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                pages.append(json.loads(line))
    return pages


def head_size(session, url):
    #a HEAD asks for the headers only, so this costs nothing but the round trip
    try:
        answer = session.head(url, timeout=20, allow_redirects=True)
        length = answer.headers.get("Content-Length")
        if length is None and answer.status_code < 400:
            #a site that will not answer a HEAD properly is asked for the first byte instead
            answer = session.get(url, timeout=20, stream=True, headers={"Range": "bytes=0-0"})
            length = (answer.headers.get("Content-Range") or "").rsplit("/", 1)[-1]
            answer.close()
        return int(length) if length and str(length).isdigit() else None
    except (requests.RequestException, ValueError):
        return None


def fill_sizes(path, pages, workers=6):
    #the size of an image is what identifies a page whose filename was changed years ago. asked once and
    #written back into the cache, so this only ever happens to pages that do not have it yet
    wanted = [page for page in pages if page.get("src") and page.get("bytes") is None]
    if not wanted:
        return 0
    print("Asking the site how big {0} image(s) are ...".format(len(wanted)))
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for page, size in zip(wanted, pool.map(lambda page: head_size(session, page["src"]), wanted)):
            page["bytes"] = size
            done += 1
            if done % 100 == 0:
                print("  {0} of {1}".format(done, len(wanted)))
    missed = [page["n"] for page in wanted if page.get("bytes") is None]
    if missed:
        print("  {0} image(s) would not say how big they are: {1}{2}".format(
            len(missed), missed[:6], "..." if len(missed) > 6 else ""))
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        for page in pages:
            f.write(json.dumps(page) + chr(10))
    os.replace(spare, path)
    return len(wanted) - len(missed)


def read_metadata(folder):
    try:
        with open(os.path.join(folder, metadata_file), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def longest_run(pairs):
    #anchors have to agree with each other: keep the longest set that runs forwards through both lists
    #and drop the rest, rather than trusting a name that happens to appear twice
    best = []
    for at, pair in enumerate(pairs):
        run = max((best[before] for before in range(at)
                   if pairs[before][0] < pair[0] and pairs[before][1] < pair[1]), key=len, default=[])
        best.append(run + [pair])
    return max(best, key=len, default=[])


def unique_pairs(by_page, by_file):
    #only what points at exactly one thing on each side: anything ambiguous is no use as an anchor
    pairs = []
    for value, wheres in by_page.items():
        heres = by_file.get(value)
        if len(wheres) == 1 and heres and len(heres) == 1:
            pairs.append((wheres[0], heres[0]))
    return pairs


def align(pages, files, folder=None):
    #pages are what the walk saw, in order; files are what is on disk, in order. the answer is which file
    #each page was saved as. anchors - pages whose image name is still recognisable in a filename - pin
    #positions exactly; between two anchors, a stretch that holds the same number of each lines up one to
    #one. a stretch where the counts differ is left unaligned and reported rather than guessed at.
    #by name: the page whose image is still recognisable in a filename
    name_pages, name_files = {}, {}
    for at, page in enumerate(pages):
        if page.get("file"):
            name_pages.setdefault(page_key(page["file"]), []).append(at)
    for at, name in enumerate(files):
        name_files.setdefault(page_key(name), []).append(at)

    #by size: what identifies a page whose file was renamed. the bytes on disk are the bytes the site
    #sent, so an exact match on a size nothing else shares is as good as a name
    size_pages, size_files = {}, {}
    if folder:
        for at, page in enumerate(pages):
            if page.get("bytes"):
                size_pages.setdefault(page["bytes"], []).append(at)
        for at, name in enumerate(files):
            try:
                size_files.setdefault(os.path.getsize(os.path.join(folder, name)), []).append(at)
            except OSError:
                pass

    found, why = {}, {}
    for at, to in unique_pairs(size_pages, size_files):
        found[at], why[at] = to, "size"
    #a name that agrees is no extra information, and a name that disagrees is the weaker of the two
    for at, to in unique_pairs(name_pages, name_files):
        if at not in found:
            found[at], why[at] = to, "name"
    anchors = longest_run(sorted(found.items()))

    aligned = [None] * len(pages)
    how = [None] * len(pages)
    for at, to in anchors:
        aligned[at], how[at] = files[to], why[at]

    trouble = []
    edges = [(-1, -1)] + anchors + [(len(pages), len(files))]
    for (page_from, file_from), (page_to, file_to) in zip(edges, edges[1:]):
        pages_between = page_to - page_from - 1
        files_between = file_to - file_from - 1
        if pages_between <= 0 and files_between <= 0:
            continue
        where = "pages {0}-{1}".format(page_from + 2, page_to) if pages_between else "after page {0}".format(page_to)
        if files_between == 0:
            #the comic has these and this folder does not, which is a gap to fill, not a puzzle to solve
            continue
        if pages_between == files_between:
            for step in range(pages_between):
                aligned[page_from + 1 + step] = files[file_from + 1 + step]
                how[page_from + 1 + step] = "order"
        else:
            trouble.append({
                "where": where,
                "pages": pages_between,
                "files": files_between,
                "detail": "{0} page(s) walked but {1} file(s) held".format(pages_between, files_between),
            })
    return aligned, how, anchors, trouble


def anchor_kinds(pages, files, anchors, folder):
    #how each anchor was recognised, for the report: by its name, or by its size
    kinds = {"name": 0, "size": 0}
    for at, to in anchors:
        same_name = pages[at].get("file") and page_key(pages[at]["file"]) == page_key(files[to])
        kinds["name" if same_name else "size"] += 1
    return kinds


def verify(folder, files, pages, aligned):
    #every placement can be checked, not just the anchored ones: the file on disk should be as big as the
    #site says its image is. a size that differs is not proof of anything on its own - a comic that moved
    #host years ago serves re-encoded images that no longer match what was downloaded then. what does
    #prove something is the site's size matching a DIFFERENT file in this folder: that is a page sitting
    #where another page's file is, which is exactly what a wrong alignment looks like.
    held_sizes = {}
    for name in files:
        try:
            held_sizes.setdefault(os.path.getsize(os.path.join(folder, name)), []).append(name)
        except OSError:
            pass
    agree, changed, conflict = 0, 0, []
    for page, name in zip(pages, aligned):
        if not name or not page.get("bytes"):
            continue
        held = held_sizes and next((size for size, names in held_sizes.items() if name in names), None)
        if held == page["bytes"]:
            agree += 1
        elif page["bytes"] in held_sizes:
            conflict.append((page["n"], name, held_sizes[page["bytes"]][:2]))
        else:
            changed += 1
    return agree, changed, conflict


def describe(folder, pages, files, aligned, how, anchors, trouble):
    matched = [name for name in aligned if name]
    spare = [name for name in files if name not in set(matched)]
    print("{0}".format(folder))
    ways = ", ".join("{0} by {1}".format(how.count(way), way) for way in ("size", "name", "order")
                     if how.count(way))
    print("  {0} pages walked, {1} files held, {2} lined up ({3})".format(
        len(pages), len(files), len(matched), ways or "none"))
    if anchors:
        kinds = anchor_kinds(pages, files, anchors, folder)
        first, last = anchors[0], anchors[-1]
        print("  {0} anchor(s) agree ({1} by name, {2} by size), from page {3} ({4}) to page {5} ({6})".format(
            len(anchors), kinds["name"], kinds["size"], first[0] + 1, files[first[1]],
            last[0] + 1, files[last[1]]))
    else:
        print("  no filename anchors: every page was renamed, so this rests on the counts matching")
    missing = [page for page, name in zip(pages, aligned) if not name]
    if missing:
        print("  {0} page(s) the comic has and this folder does not:".format(len(missing)))
        for page in missing[:12]:
            print("      page {0:<5} {1}".format(page["n"], page["url"]))
        if len(missing) > 12:
            print("      ... and {0} more".format(len(missing) - 12))
    if spare:
        print("  {0} file(s) no page claims: {1}{2}".format(
            len(spare), spare[:4], "..." if len(spare) > 4 else ""))
    agree, changed, conflict = verify(folder, files, pages, aligned)
    print("  checked against the site's own sizes: {0} match exactly, {1} differ (re-uploaded since, "
          "and their size is held by no other file here), {2} land on another page's file".format(
              agree, changed, len(conflict)))
    for n, name, others in conflict[:8]:
        print("      page {0:<5} placed at {1:<26} but its size belongs to {2}".format(n, name[:26], others))
    if len(conflict) > 8:
        print("      ... and {0} more".format(len(conflict) - 8))
    for problem in trouble:
        print("  UNRESOLVED {0}: {1}".format(problem["where"], problem["detail"]))
    #what chaptering needs is that every file is placed. a page the comic has and this folder does not
    #leaves a gap in the reading, but the files either side of it are still placed correctly.
    settled = not trouble and not spare and not conflict
    if settled and missing:
        print("  settled: every file is placed. The {0} page(s) above are missing from this folder, "
              "not misplaced.".format(len(missing)))
    elif settled:
        print("  settled: every page has a file and every file has a page")
    else:
        print("  NOT settled: fix the above, or align by hand, before chaptering")
    return settled


def remember_cache(folder, path):
    #written into the comic so another machine, where this folder has a different path, still finds it
    metadata = read_metadata(folder)
    if not metadata:
        return
    history = metadata.setdefault("history", {})
    if history.get("index_cache") != os.path.basename(path):
        history["index_cache"] = os.path.basename(path)
        write_metadata(folder, metadata)


def save_alignment(path, folder, pages, aligned, how, settled):
    out = {
        "comic": folder,
        "settled": settled,
        "pages": [{"n": page["n"], "url": page["url"], "title": page.get("title"),
                   "src": page.get("src"), "file": name, "how": way}
                  for page, name, way in zip(pages, aligned, how)],
    }
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
        f.write(chr(10))
    os.replace(spare, path)
    return path


def write_metadata(folder, metadata):
    path = os.path.join(folder, metadata_file)
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
        f.write(chr(10))
    os.replace(spare, path)


def gap_notes(pages, aligned):
    #what the comic has that this folder does not, and pages the site shows with no image at all - a flash
    #page, usually. written into the metadata so the next person to look does not have to work it out
    #again, and so a page saved by hand is not mistaken for a mistake later.
    gaps, oddities = [], []
    for page, name in zip(pages, aligned):
        imageless = not page.get("src")
        if not name:
            gaps.append({
                "page": page["n"], "url": page["url"], "title": page.get("title"),
                "note": "the site shows no image on this page, which is usually flash; nothing saved"
                        if imageless else "no file here for this page",
            })
        elif imageless:
            oddities.append({
                "page": page["n"], "url": page["url"], "file": name,
                "note": "the site shows no image on this page, so this file was made by hand",
            })
    return gaps, oddities


def save_gaps(folder, pages, aligned):
    metadata = read_metadata(folder)
    if not metadata:
        print("  no metadata here, so the gaps were not written down")
        return 0
    gaps, oddities = gap_notes(pages, aligned)
    history = metadata.setdefault("history", {})
    #kept even when empty, so "this comic has been looked at and has no gaps" is a thing the file can say
    history["gaps"] = gaps
    if oddities:
        history["hand_made"] = oddities
    elif "hand_made" in history:
        del history["hand_made"]
    history["gaps_checked"] = time_stamp()
    write_metadata(folder, metadata)
    print("  wrote {0} gap(s) and {1} hand-made page(s) into {2}".format(
        len(gaps), len(oddities), os.path.join(folder, metadata_file)))
    return len(gaps)


def time_stamp():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- where the chapters are ----------------
def same_page(url):
    #one page can be written several ways - http or https, with or without www or a trailing slash - so
    #everything is reduced to the part that actually identifies it before anything is compared
    url = (url or "").strip()
    url = re.sub(r'^https?://', '', url, flags=re.I)
    url = re.sub(r'^www\.', '', url, flags=re.I)
    return url.rstrip('/').lower()


class ArchiveReader(html.parser.HTMLParser):
    #reads a comic's archive page as a sequence of two things: headings, and links. what a heading looks
    #like differs from site to site - a real heading tag on one, a bold line or a table cell on another -
    #so anything that could be one is kept, and a link is later put under whichever came last before it.
    heading_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "b", "strong", "legend", "caption", "summary")

    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.events = []
        self.depth = 0
        self.heading = None
        self.rank = 1
        self.link = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        got = dict(attrs)
        if tag == "a" and got.get("href"):
            self.link = got["href"]
            self.text = []
            return
        #whole words only: a class called comic-archive-date holds "arc" inside "archive" and is a date,
        #not a heading
        words = set(re.split(r'[^a-z]+', "{0} {1}".format(got.get("class") or "", got.get("id") or "").lower()))
        self.rank = 0 if re.match(r'^h[1-6]$', tag) else 1
        looks_like = tag in self.heading_tags or bool(
            words & {"chapter", "chapters", "arc", "arcs", "volume", "book", "story", "storyline"})
        if looks_like:
            self.heading = tag
            self.text = []

    def handle_endtag(self, tag):
        said = re.sub(r'\s+', ' ', "".join(self.text)).strip()
        if tag == "a" and self.link is not None:
            self.events.append(("link", self.link, said))
            self.link = None
        elif self.heading and tag == self.heading:
            if said:
                self.events.append(("heading", said, self.rank))
            self.heading = None
        self.text = []

    def handle_data(self, data):
        if self.link is not None or self.heading:
            self.text.append(data)


def read_archive(url, browser=False, script=None):
    if browser:
        #for an archive a plain fetch comes back empty on, because the page builds itself with javascript
        done = subprocess.run([sys.executable, script or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mirror_base.py"), "--page-source", url],
            capture_output=True, text=True, timeout=300)
        return done.stdout
    answer = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    answer.raise_for_status()
    return answer.text


def chapters_from_events(events, where, base=""):
    #a chapter starts at the first page link after a heading. several headings can sit together - a title
    #and the summary underneath it - so the one that reads most like a title wins: a real heading tag
    #first, and the earliest of those.
    found, waiting, listed = [], [], 0
    for kind, first, second in events:
        if kind == "heading":
            waiting.append((second if second is not None else 1, len(waiting), first))
            continue
        at = where.get(same_page(urljoin(base, first)))
        if at is None:
            continue
        listed += 1
        if waiting or not found:
            #the most heading-like wins, and among equals the one nearest the link: a page's own banner
            #sits far above the first chapter's title, and a summary sits just under it
            label = (min(waiting, key=lambda held: (held[0], -held[1]))[2] if waiting
                     else "Chapter {0}".format(len(found) + 1))
            found.append({"label": label, "start_page": at, "pages_listed": []})
            waiting = []
        found[-1]["pages_listed"].append(at)
        found[-1]["start_page"] = min(found[-1]["start_page"], at)
    return found, listed


def chapters_from_archive(url, pages, browser=False, script=None):
    #the archive page says where each chapter starts; the walk says where every page sits. matching one
    #against the other needs no knowledge of the site beyond which links are pages of this comic.
    where = {same_page(page["url"]): page["n"] for page in pages}
    reader = ArchiveReader()
    reader.feed(read_archive(url, browser, script))
    #plenty of archives link their pages relatively, so each is read against the archive's own address
    return chapters_from_events(reader.events, where, url)


def chapters_from_urls(pages):
    #a comic whose addresses carry the chapter, like /c4/p7 or /ss/4-7: the chapter is the number that
    #never goes down while another number resets underneath it. a part that never changes at all is the
    #comic's own name in the path, not a chapter.
    split = []
    for page in pages:
        bits = re.split(r'(\d+)', same_page(page["url"]))
        split.append([int(bit) if bit.isdigit() else bit for bit in bits])
    width = min(len(bits) for bits in split)
    if not split or width < 2:
        return []
    best = None
    for at in range(width):
        column = [bits[at] for bits in split]
        if not all(isinstance(value, int) for value in column):
            continue
        if len(set(column)) < 2 or any(b < a for a, b in zip(column, column[1:])):
            continue #a chapter number only ever goes up
        resets = 0
        for under in range(at + 1, width):
            below = [bits[under] for bits in split]
            if not all(isinstance(value, int) for value in below):
                continue
            resets += sum(1 for step in range(1, len(column))
                          if column[step] > column[step - 1] and below[step] < below[step - 1])
        changes = sum(1 for a, b in zip(column, column[1:]) if a != b)
        if changes and (best is None or (resets, -changes) > (best[1], -best[2])):
            best = (at, resets, changes)
    if best is None or best[1] == 0:
        return []
    at = best[0]
    found = []
    for page, bits in zip(pages, split):
        number = bits[at]
        if not found or found[-1]["number"] != number:
            found.append({"label": "Chapter {0}".format(number), "number": number,
                          "start_page": page["n"], "pages_listed": []})
        found[-1]["pages_listed"].append(page["n"])
    return found


def chapters_from_list(path, pages):
    #a list of addresses, one for each chapter start, with an optional title after it
    where = {same_page(page["url"]): page["n"] for page in pages}
    found, unknown = [], []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            url, _, label = line.partition('|') if '|' in line else (line.split()[0], None, ' '.join(line.split()[1:]))
            at = where.get(same_page(url.strip()))
            if at is None:
                unknown.append(url)
                continue
            found.append({"label": label.strip() or "Chapter {0}".format(len(found) + 1),
                          "start_page": at, "pages_listed": [at]})
    for url in unknown:
        print("  no page of this comic is at {0}".format(url))
    return found


def settle_chapters(found, pages, shift=0):
    #chapters are read in the order the comic is read, and each one runs until the next one starts, so
    #anything between them - filler, guest art, a flash page with no file - stays where it was published
    for chapter in found:
        chapter["start_page"] = max(1, min(len(pages), chapter["start_page"] + shift))
    found = sorted(found, key=lambda chapter: chapter["start_page"])
    settled, seen = [], set()
    for chapter in found:
        if chapter["start_page"] in seen:
            continue #two headings pointing at one page is one chapter
        seen.add(chapter["start_page"])
        settled.append(chapter)
    by_page = {page["n"]: page for page in pages}
    for at, chapter in enumerate(settled):
        ends = settled[at + 1]["start_page"] - 1 if at + 1 < len(settled) else pages[-1]["n"]
        chapter["number"] = at + 1
        chapter["end_page"] = ends
        chapter["pages"] = ends - chapter["start_page"] + 1
        start = by_page.get(chapter["start_page"], {})
        chapter["start_url"] = start.get("url")
        chapter["start_file"] = start.get("file")
        chapter.pop("pages_listed", None)
    return settled


def show_chapters(folder, chapters, pages, listed=None):
    print("{0}: {1} chapter(s) over {2} page(s)".format(folder, len(chapters), len(pages)))
    if listed is not None:
        print("  the archive listed {0} of this comic's {1} pages".format(listed, len(pages)))
    before = chapters[0]["start_page"] - 1 if chapters else 0
    if before:
        print("  {0} page(s) come before the first chapter starts".format(before))
    print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}".format("no", "label", "from", "to", "pages", "starts at"))
    for chapter in chapters:
        print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}".format(
            chapter["number"], (chapter["label"] or "")[:44], chapter["start_page"], chapter["end_page"],
            chapter["pages"], (chapter["start_file"] or "?")))
    odd = [c for c in chapters if c["pages"] <= 1]
    if odd:
        print("  {0} chapter(s) hold one page or none, which usually means a heading was read wrongly: "
              "{1}".format(len(odd), [c["number"] for c in odd[:8]]))


def save_chapters(folder, chapters, source, source_url=None):
    metadata = read_metadata(folder)
    if not metadata:
        print("  no metadata here, so the chapters were not saved")
        return 1
    metadata["chapters"] = {
        "source": source,
        "source_url": source_url,
        "checked": time_stamp(),
        "list": [{"number": c["number"], "label": c["label"], "start_page": c["start_page"],
                  "end_page": c["end_page"], "pages": c["pages"], "start_url": c["start_url"],
                  "start_file": c["start_file"]} for c in chapters],
    }
    write_metadata(folder, metadata)
    print("  saved {0} chapter(s) into {1}".format(len(chapters), os.path.join(folder, metadata_file)))
    return 0


def compare_chapters(was, now):
    #what changed, in the terms that matter: a chapter added at the end is safe to take, while one that
    #moved or vanished means pages would leave archives that already hold them
    was = was or []
    older = [(c["start_page"], c.get("label")) for c in was]
    newer = [(c["start_page"], c.get("label")) for c in now]
    if older == newer[:len(older)]:
        return "same" if len(newer) == len(older) else "longer", newer[len(older):]
    moved = [old for old, fresh in zip(older, newer) if old != fresh]
    return "changed", moved


def plan(folder, args):
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    metadata = read_metadata(folder)
    known = metadata.get("chapters") or {}
    if not args.archive and not args.list and known.get("source") == "archive" and known.get("source_url"):
        #the comic remembers where its chapters are listed, so keeping them current needs no arguments
        args.archive = known["source_url"]
        print("Reading the archive this comic remembers: {0}".format(args.archive))
    listed = None
    if args.archive:
        found, listed = chapters_from_archive(args.archive, pages, args.browser, args.script)
        source, source_url = "archive", args.archive
    elif args.list:
        found, source, source_url = chapters_from_list(args.list, pages), "list", None
    else:
        found, source, source_url = chapters_from_urls(pages), "urls", None
        if not found:
            print("Nothing in this comic's addresses says where a chapter starts. Give --archive with its "
                  "archive page, or --list with a file of chapter start addresses.")
            return 1
    if not found:
        print("No chapters found.")
        return 1
    chapters = settle_chapters(found, pages, args.shift)
    show_chapters(folder, chapters, pages, listed)
    how, what = compare_chapters(known.get("list"), chapters)
    if known.get("list"):
        if how == "same":
            print("  the same chapters as before.")
        elif how == "longer":
            print("  {0} chapter(s) more than before: {1}".format(
                len(what), ", ".join("{0} at page {1}".format(label, at) for at, label in what[:4])))
        else:
            print("  WARNING: this moves chapters that already have archives written for them: {0}{1}".format(
                ["page {0}".format(at) for at, label in what[:4]], "..." if len(what) > 4 else ""))
    if not args.save:
        print("  nothing saved. Run it again with --save once this looks right.")
        return 0
    if how == "changed" and not args.force:
        print("  nothing saved, because pages would move between archives that already exist. Look at it, "
              "then run it again with --force if that is what you want.")
        return 1
    return save_chapters(folder, chapters, source, source_url)


# ---------------- one archive per chapter ----------------
def tidy_name(text):
    #a label becomes part of a filename, so anything a filesystem or a reader would choke on goes
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', text or "")
    text = re.sub(r'\s+', ' ', text).strip(' .')
    return text[:70].strip() or "Chapter"


def chapter_folder(folder, metadata, root=None, given=None):
    #the comic's own folder inside the archive shelf: a reader that dislikes loose .cbz files in a shelf
    #is happy with one folder per comic. a comic whose single archive already sits in a folder of its own
    #name is given that folder, rather than another one nested inside it.
    if given:
        return given
    cbz = (metadata.get("settings") or {}).get("cbz_path")
    if not cbz:
        return os.path.abspath(folder) + "_chapters"
    full = cbz if os.path.isabs(cbz) or not root else os.path.join(root, cbz.replace('/', os.sep))
    name = os.path.basename(os.path.abspath(folder))
    if os.path.basename(os.path.dirname(full)).lower() == name.lower():
        return os.path.dirname(full)
    return full[:-4] if full.lower().endswith(".cbz") else full


def chapter_file(folder, chapter):
    return "{0} - c{1:03d} - {2}.cbz".format(os.path.basename(os.path.abspath(folder)),
                                             chapter["number"], tidy_name(chapter["label"]))


def comic_info(folder, chapter, count, names):
    #what a reader reads to know this is chapter N of a series rather than a loose pile of pictures
    def escaped(text):
        return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <Series>{0}</Series>'.format(escaped(os.path.basename(os.path.abspath(folder)))),
             '  <Number>{0}</Number>'.format(chapter["number"]),
             '  <Count>{0}</Count>'.format(count),
             '  <Title>{0}</Title>'.format(escaped(chapter["label"])),
             '  <PageCount>{0}</PageCount>'.format(len(names))]
    if chapter.get("start_url"):
        lines.append('  <Web>{0}</Web>'.format(escaped(chapter["start_url"])))
    lines.append('  <Notes>Made by chapters.py from pages {0} to {1}</Notes>'.format(
        chapter["start_page"], chapter["end_page"]))
    lines.append('</ComicInfo>')
    return chr(10).join(lines) + chr(10)


def chapter_contents(folder, chapters, pages):
    #which files belong to which chapter, in reading order. a page the comic has and this folder does not
    #simply is not there; the pages either side of it still sit in the right chapter.
    by_page = {page["n"]: page for page in pages}
    parcels = []
    for chapter in chapters:
        names = [by_page[n]["file"] for n in range(chapter["start_page"], chapter["end_page"] + 1)
                 if by_page.get(n) and by_page[n].get("file")]
        parcels.append((chapter, names))
    #pages saved since the chapters were worked out belong to the chapter still being published, which is
    #the last one. they are added in the order they were saved, which is the order they came out.
    if parcels:
        known = {name for _, names in parcels for name in names}
        held = folder_pages(folder)
        last_known = max((at for at, name in enumerate(held) if name in known), default=-1)
        fresh = [name for name in held[last_known + 1:] if name not in known]
        if fresh:
            parcels[-1][1].extend(fresh)
            print("  {0} page(s) saved since the chapters were worked out join chapter {1}".format(
                len(fresh), parcels[-1][0]["number"]))
    return parcels


def already_packed(path, names, folder):
    #an archive only needs writing again if what it holds is not what it should hold
    if not os.path.exists(path):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            held = {info.filename: info.file_size for info in zf.infolist() if not info.filename.endswith('/')}
    except (OSError, zipfile.BadZipFile):
        return False
    wanted = {}
    for name in names:
        try:
            wanted[name] = os.path.getsize(os.path.join(folder, name))
        except OSError:
            return False
    held.pop("ComicInfo.xml", None)
    return held == wanted


def pack(folder, args):
    metadata = read_metadata(folder)
    chapters = (metadata.get("chapters") or {}).get("list")
    if not chapters:
        print("ERROR: no chapters worked out for {0} yet. Run: chapters.py chapters {0} --archive ...".format(folder))
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    shelf = chapter_folder(folder, metadata, args.root, args.cbz_folder)
    parcels = chapter_contents(folder, chapters, pages)
    held = {name for _, names in parcels for name in names}
    on_disk = set(folder_pages(folder))
    astray = sorted(on_disk - held)
    if astray:
        print("ERROR: {0} file(s) belong to no chapter, so nothing was written: {1}{2}".format(
            len(astray), astray[:5], "..." if len(astray) > 5 else ""))
        return 1

    print("{0}: {1} chapter(s) into {2}".format(folder, len(parcels), shelf))
    todo = [(chapter, names) for chapter, names in parcels
            if not already_packed(os.path.join(shelf, chapter_file(folder, chapter)), names, folder)]
    print("  {0} to write, {1} already as they should be".format(len(todo), len(parcels) - len(todo)))
    for chapter, names in parcels[:100]:
        mark = "write" if (chapter, names) in todo else "keep "
        print("  {0} c{1:03d} {2:<44} {3:>4} page(s)  {4}".format(
            mark, chapter["number"], tidy_name(chapter["label"])[:44], len(names),
            chapter_file(folder, chapter)[:60]))
    if args.dry_run:
        print("Nothing was written. Run it again without --dry-run.")
        return 0

    if not os.path.isdir(shelf):
        os.makedirs(shelf)
    written = 0
    for chapter, names in todo:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        spare = path + ".packing"
        with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr("ComicInfo.xml", comic_info(folder, chapter, len(parcels), names))
            for name in names:
                zf.write(os.path.join(folder, name), name)
        os.replace(spare, path)
        written += 1
        print("  wrote {0} ({1} page(s))".format(os.path.basename(path), len(names)))
    print("Wrote {0} chapter archive(s).".format(written))

    kept = verify_chapters(folder, shelf, parcels)
    if kept is not True:
        return 1
    metadata = read_metadata(folder)
    block = metadata.setdefault("chapters", {})
    block["folder"] = os.path.relpath(shelf, args.root).replace(os.sep, '/') if args.root else shelf
    block["packed"] = time_stamp()
    #the single archive is no longer the thing being kept up to date, so a scrape must stop rebuilding it
    if args.replace:
        metadata.setdefault("settings", {})["cbz"] = False
    write_metadata(folder, metadata)

    if args.replace:
        return drop_single(folder, metadata, args)
    return 0


def verify_chapters(folder, shelf, parcels):
    #every page has to be in exactly one chapter archive, at the size it is on disk, before the single
    #archive that holds them all can be given up
    seen, trouble = {}, []
    for chapter, names in parcels:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        try:
            with zipfile.ZipFile(path) as zf:
                held = {info.filename: info.file_size for info in zf.infolist()
                        if info.filename != "ComicInfo.xml" and not info.filename.endswith('/')}
        except (OSError, zipfile.BadZipFile) as error:
            trouble.append("c{0:03d}: {1}".format(chapter["number"], error))
            continue
        for name in names:
            size = os.path.getsize(os.path.join(folder, name))
            if held.get(name) != size:
                trouble.append("c{0:03d}: {1} is {2} in the archive, {3} on disk".format(
                    chapter["number"], name, held.get(name), size))
            if name in seen:
                trouble.append("{0} is in both c{1:03d} and c{2:03d}".format(name, seen[name], chapter["number"]))
            seen[name] = chapter["number"]
    missing = sorted(set(folder_pages(folder)) - set(seen))
    for name in missing[:5]:
        trouble.append("{0} is in no chapter archive".format(name))
    if trouble:
        print("Checked the chapter archives and found {0} problem(s):".format(len(trouble)))
        for line in trouble[:10]:
            print("  {0}".format(line))
        return False
    print("Checked: all {0} page(s) are in exactly one chapter archive, at the size they are on disk.".format(
        len(seen)))
    return True


def drop_single(folder, metadata, args):
    cbz = (metadata.get("settings") or {}).get("cbz_path")
    if not cbz:
        return 0
    full = cbz if os.path.isabs(cbz) else os.path.join(args.root or os.path.dirname(folder),
                                                       cbz.replace('/', os.sep))
    if not os.path.exists(full):
        return 0
    size = os.path.getsize(full)
    os.remove(full)
    print("Removed {0} ({1:.0f} MB); the chapter archives hold every page it held.".format(full, size / 1e6))
    return 0


# ---------------- fetching pages again ----------------
def joined_pages(folder, args):
    #the alignment says which file is which page; the walk says how big the site's copy is
    cache = index_path(folder, args.root, args)
    alignment = cache.replace(".jsonl", ".align.json")
    if not os.path.exists(alignment):
        print("ERROR: {0} has not been lined up yet. Run: chapters.py index {0}".format(folder))
        return None
    sizes = {page["n"]: page.get("bytes") for page in read_index(cache)}
    saved = json.load(open(alignment, encoding='utf-8'))
    if not saved.get("settled"):
        print("WARNING: this comic's alignment is not settled, so which file is which page is not certain.")
    return [dict(page, bytes=sizes.get(page["n"])) for page in saved["pages"]]


def refetch(folder, args):
    #the copies in a library that came from somewhere else are often compressed harder than what the site
    #serves. this fetches those pages again under the names they already have, so nothing else has to change
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    wanted = []
    for page in pages:
        if not page["file"] or not page.get("src"):
            continue
        path = os.path.join(folder, page["file"])
        try:
            held = os.path.getsize(path)
        except OSError:
            continue
        if args.all or (page["bytes"] and held != page["bytes"]):
            wanted.append((page, held))
    if not wanted:
        print("Nothing to fetch again: every page is already the size the site serves.")
        return 0

    growth = sum((page["bytes"] or held) - held for page, held in wanted)
    print("{0} page(s) to fetch again, {1:.0f} MB held here now, {2:.0f} MB on the site ({3:+.0f} MB)".format(
        len(wanted), sum(held for _, held in wanted) / 1e6,
        sum((page["bytes"] or held) for page, held in wanted) / 1e6, growth / 1e6))
    if args.dry_run:
        for page, held in wanted[:8]:
            print("  page {0:<5} {1:<26} {2} -> {3} bytes".format(
                page["n"], page["file"][:26], held, page["bytes"]))
        if len(wanted) > 8:
            print("  ... and {0} more".format(len(wanted) - 8))
        print("Nothing was changed. Run it again without --dry-run to fetch them.")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    done, kept, failed = 0, 0, []
    for page, held in wanted:
        path = os.path.join(folder, page["file"])
        try:
            answer = session.get(page["src"], timeout=120)
            answer.raise_for_status()
            fresh = answer.content
        except requests.RequestException as error:
            failed.append((page["n"], str(error)[:80]))
            continue
        #only replaced once the new copy is in hand and is the size the site said, so a failed fetch
        #cannot leave a page half written or lose the copy that was already there
        if page["bytes"] and len(fresh) != page["bytes"]:
            failed.append((page["n"], "fetched {0} bytes, expected {1}".format(len(fresh), page["bytes"])))
            continue
        if len(fresh) <= held:
            kept += 1
            continue
        spare = path + ".fetching"
        with open(spare, 'wb') as f:
            f.write(fresh)
        os.replace(spare, path)
        done += 1
        if done % 25 == 0:
            print("  {0} of {1} replaced".format(done, len(wanted)))
    print("Replaced {0} page(s); left {1} alone as no better than what was here.".format(done, kept))
    for n, why in failed[:8]:
        print("  page {0} was not replaced: {1}".format(n, why))
    if len(failed) > 8:
        print("  ... and {0} more".format(len(failed) - 8))
    if done and args.repack:
        repack(folder, args)
    elif done:
        print("The .cbz still holds the old copies. Run again with --repack, or repack it yourself.")
    return 1 if failed else 0


def repack(folder, args):
    #a zip cannot replace an entry in place, so the archive is written afresh beside the old one and
    #swapped in only once it is complete and holds every page
    cbz = args.cbz
    if not cbz:
        metadata = read_metadata(folder)
        cbz = (metadata.get("settings") or {}).get("cbz_path")
        if cbz and args.root and not os.path.isabs(cbz):
            cbz = os.path.join(args.root, cbz)
    if not cbz or not os.path.exists(cbz):
        print("No archive found to repack; pass --cbz with its path.")
        return 1
    names = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    with zipfile.ZipFile(cbz) as zf:
        prefix = os.path.basename(os.path.abspath(folder)) + '/'
        held = zf.namelist()
        prefix = prefix if held and all(name.startswith(prefix) for name in held) else ''
    spare = cbz + ".packing"
    print("Repacking {0} ({1} file(s)) ...".format(cbz, len(names)))
    with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
        for name in names:
            zf.write(os.path.join(folder, name), prefix + name)
    with zipfile.ZipFile(spare) as zf:
        packed = [name for name in zf.namelist() if not name.endswith('/')]
    if len(packed) != len(names):
        os.remove(spare)
        print("ERROR: the new archive holds {0} of {1} files, so the old one was left alone.".format(
            len(packed), len(names)))
        return 1
    shutil.move(spare, cbz)
    print("  {0} now holds every page as it is on disk.".format(cbz))
    return 0


def walk(folder, args):
    #the slow part: mirror_base follows the comic from its first page, saving nothing
    cache = index_path(folder, args.root, args)
    start = args.start
    metadata = read_metadata(folder)
    history = metadata.get("history") or {}
    if not start and not os.path.exists(cache):
        if history.get("first_page_number") in (0, 1) and history.get("first_page_url"):
            start = history["first_page_url"]
        else:
            start = (metadata.get("settings") or {}).get("url")
            if not start:
                print("ERROR: nothing says where {0} starts. Pass --start with its first page.".format(folder))
                return None
            print("NOTE: this comic's metadata only records page {0} at {1}, so the walk starts from where "
                  "it left off and follows the comic's first-page link back.".format(
                      history.get("first_page_number"), start))
            args.first = True
    command = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_base.py"),
               "--index", cache]
    if args.first:
        command.append("--index-first")
    if args.limit:
        command += ["--index-limit", str(args.limit)]
    if start:
        command.append(start)
    else:
        #carrying on, so the walk works out where it got to from the cache itself
        command.append(read_index(cache)[-1]["url"])
    print("Walking {0} ...".format(folder))
    done = subprocess.run(command, text=True)
    if done.returncode != 0:
        print("The walk stopped early (exit {0}); what it got is kept and running it again carries "
              "on.".format(done.returncode))
    return cache


def do_align(folder, args):
    cache = index_path(folder, args.root, args)
    if not os.path.exists(cache):
        print("ERROR: no index for {0} yet. Run: chapters.py index {1}".format(folder, folder))
        return 2
    pages = read_index(cache)
    files = folder_pages(folder)
    fill_sizes(cache, pages)
    aligned, how, anchors, trouble = align(pages, files, folder)
    settled = describe(folder, pages, files, aligned, how, anchors, trouble)
    where = save_alignment(cache.replace(".jsonl", ".align.json"), folder, pages, aligned, how, settled)
    remember_cache(folder, cache)
    print("  written to {0}".format(where))
    if settled:
        save_gaps(folder, pages, aligned)
    return 0 if settled else 1


def setup():
    params = argparse.ArgumentParser(
        description="Line a comic's saved files up with the pages they came from.")
    params.add_argument("what", choices=["index", "align", "show", "chapters", "pack", "refetch", "repack"],
                        help="index: walk the comic and line it up. align: line up a walk already done. "
                             "show: what the last alignment says. refetch: fetch again any page whose file "
                             "is not what the site serves. chapters: work out where the chapters start. "
                             "pack: write one .cbz per chapter. "
                             "repack: write the .cbz afresh from the folder.")
    params.add_argument("folder", help="The comic's folder.")
    params.add_argument("--start", default=None, help="The comic's first page, when its metadata does not know.")
    params.add_argument("--first", action='store_true', default=False,
                        help="Follow the comic's first-page link before walking.")
    params.add_argument("--limit", type=int, default=0, help="Stop the walk after this many pages.")
    params.add_argument("--root", default=None, help="Library folder, used to name the cache.")
    params.add_argument("--dry-run", "-n", action='store_true', default=False,
                        help="With refetch, say what would be fetched and change nothing.")
    params.add_argument("--all", action='store_true', default=False,
                        help="With refetch, fetch every page again, not only those that differ.")
    params.add_argument("--repack", action='store_true', default=False,
                        help="With refetch, write the .cbz afresh afterwards so it holds the new copies.")
    params.add_argument("--cbz", default=None, help="The archive to repack, when the metadata does not say.")
    params.add_argument("--cbz-folder", default=None,
                        help="With pack, where the chapter archives go. Defaults to the comic's own folder "
                             "inside the archive shelf.")
    params.add_argument("--replace", action='store_true', default=False,
                        help="With pack, remove the single archive once every page is checked to be in a "
                             "chapter archive, and stop scrapes rebuilding it.")
    params.add_argument("--archive", default=None,
                        help="With chapters, the comic's archive page, which is read for chapter headings.")
    params.add_argument("--list", default=None,
                        help="With chapters, a file of chapter start addresses, one per line, each "
                             "optionally followed by | and a title.")
    params.add_argument("--browser", action='store_true', default=False,
                        help="With chapters, load the archive page in the browser, for a page that builds "
                             "itself with javascript.")
    params.add_argument("--shift", type=int, default=0,
                        help="With chapters, move every boundary this many pages, for an archive that "
                             "labels a chapter after its first page rather than before it.")
    params.add_argument("--force", action='store_true', default=False,
                        help="With chapters and --save, take a change that moves chapters which already "
                             "have archives, not only one that adds chapters at the end.")
    params.add_argument("--save", action='store_true', default=False,
                        help="With chapters, write what it worked out into the comic's metadata.")
    params.add_argument("--script", default=None, help="Path to mirror_base.py.")
    params.add_argument("--cache", default=None,
                        help="The walk's cache file, when it is not the one in the config folder.")
    return params.parse_args()


def main():
    args = setup()
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print("ERROR: {0} is not a folder.".format(folder))
        return 2
    if args.what == "show":
        path = index_path(folder, args.root, args).replace(".jsonl", ".align.json")
        if not os.path.exists(path):
            print("ERROR: {0} has not been lined up yet.".format(folder))
            return 2
        saved = json.load(open(path, encoding='utf-8'))
        print("{0}: {1} pages, {2}".format(saved["comic"], len(saved["pages"]),
                                           "settled" if saved["settled"] else "NOT settled"))
        for page in saved["pages"][:5] + saved["pages"][-5:]:
            print("  {0:>5}  {1:<28} {2:<6} {3}".format(page["n"], str(page["file"])[:28], page["how"] or "-",
                                                        page["url"]))
        return 0
    if args.what == "pack":
        return pack(folder, args)
    if args.what == "chapters":
        return plan(folder, args)
    if args.what == "refetch":
        return refetch(folder, args)
    if args.what == "repack":
        return repack(folder, args)
    if args.what == "index":
        if walk(folder, args) is None:
            return 2
    return do_align(folder, args)


if __name__ == "__main__":
    sys.exit(main())
