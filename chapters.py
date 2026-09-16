#works out which saved file came from which page of a comic, by walking the comic without downloading
#anything and lining that walk up against what is already on disk. the walk is the slow part and its
#result is cached; the alignment is what everything about chapters is later built on. #V 1.0

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
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


def index_path(folder, root=None):
    #the comic's own folder decides the name, and nothing else: passing a library folder or not must never
    #change which cache a comic uses. the short tag is what keeps two comics called Extras apart.
    full = os.path.abspath(folder)
    tag = hashlib.sha1(full.replace(os.sep, '/').lower().encode('utf-8')).hexdigest()[:8]
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(full)).strip('_') or "comic"
    return os.path.join(config_folder(), "index", "{0}.{1}.jsonl".format(name, tag))


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


# ---------------- fetching pages again ----------------
def joined_pages(folder, args):
    #the alignment says which file is which page; the walk says how big the site's copy is
    cache = index_path(folder, args.root)
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
    cache = index_path(folder, args.root)
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
    cache = index_path(folder, args.root)
    if not os.path.exists(cache):
        print("ERROR: no index for {0} yet. Run: chapters.py index {1}".format(folder, folder))
        return 2
    pages = read_index(cache)
    files = folder_pages(folder)
    fill_sizes(cache, pages)
    aligned, how, anchors, trouble = align(pages, files, folder)
    settled = describe(folder, pages, files, aligned, how, anchors, trouble)
    where = save_alignment(cache.replace(".jsonl", ".align.json"), folder, pages, aligned, how, settled)
    print("  written to {0}".format(where))
    if settled:
        save_gaps(folder, pages, aligned)
    return 0 if settled else 1


def setup():
    params = argparse.ArgumentParser(
        description="Line a comic's saved files up with the pages they came from.")
    params.add_argument("what", choices=["index", "align", "show", "refetch", "repack"],
                        help="index: walk the comic and line it up. align: line up a walk already done. "
                             "show: what the last alignment says. refetch: fetch again any page whose file "
                             "is not what the site serves. repack: write the .cbz afresh from the folder.")
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
    return params.parse_args()


def main():
    args = setup()
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print("ERROR: {0} is not a folder.".format(folder))
        return 2
    if args.what == "show":
        path = index_path(folder, args.root).replace(".jsonl", ".align.json")
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
