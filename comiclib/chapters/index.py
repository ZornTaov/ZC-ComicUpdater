#the record of which page is which: one line per page of the comic, in reading order, written by a walk
#that follows the comic from its first page saving nothing, or by a scrape that keeps it as it goes. the
#alignment that lines it up against the files is kept beside it.
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from comiclib.metadata import read as read_metadata, write as write_metadata, write_json
from comiclib.paths import PROJECT, index_folder, index_name

#the scraper, which a walk runs with --index to follow the comic and save nothing
MIRROR = os.path.join(PROJECT, "mirror_base.py")


def alignment_path(cache):
    #the alignment lives beside the index it was made from
    return cache.replace(".jsonl", ".align.json")


def index_path(folder, root=None, args=None):
    #the comic's own folder decides the name, and nothing else: passing a library folder or not must never
    #change which cache a comic uses
    if args is not None and getattr(args, "cache", None):
        return args.cache
    here = os.path.join(index_folder(), index_name(folder))
    if os.path.exists(here):
        return here
    #the same comic reached by another path - a share on one machine, a mount inside a container - hashes
    #differently, so the comic itself says which cache is its own and that is used when it is there
    named = ((read_metadata(folder).get("history") or {}).get("index_cache"))
    if named:
        elsewhere = os.path.join(index_folder(), named)
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
    write_json(path, out, indent=1)
    return path


def joined_pages(folder, args):
    #the alignment says which file is which page; the walk says how big the site's copy is
    cache = index_path(folder, args.root, args)
    alignment = alignment_path(cache)
    if not os.path.exists(alignment):
        print("ERROR: {0} has not been lined up yet. Run: chapters.py index {0}".format(folder))
        return None
    #a library on a network share answers slowly enough that silence looks like a hang, so every slow
    #step says what it is doing before it starts rather than after it finishes
    print("  reading which file is which page ...", flush=True)
    sizes = {page["n"]: page.get("bytes") for page in read_index(cache)}
    saved = json.load(open(alignment, encoding='utf-8'))
    if not saved.get("settled"):
        print("WARNING: this comic's alignment is not settled, so which file is which page is not certain.")
    return [dict(page, bytes=sizes.get(page["n"])) for page in saved["pages"]]


def walk(folder, args):
    #the slow part: mirror_base follows the comic from its first page, saving nothing
    cache = index_path(folder, args.root, args)
    start = args.start
    if getattr(args, "restart", False) and os.path.exists(cache):
        #a record written from somewhere other than the first page cannot be carried on from: its page
        #numbers are counted from wherever it began, and a walk resuming from its last line starts at the
        #comic's newest page and stops there. said plainly and thrown away, rather than merged into.
        held = read_index(cache)
        print("Throwing away the record of {0} page(s) in {1}, and walking from the start.".format(
            len(held), cache))
        os.remove(cache)
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
    command = [sys.executable, MIRROR, "--index", cache]
    #a walk drives the same site a scrape does, so it needs to be told the same things about it. a comic
    #whose pages are built by javascript shows nothing at all without it - not its images and not its next
    #link - so a walk without these settings ends on the page it started, having seen nothing.
    settings = metadata.get("settings") or {}
    if settings.get("javascript"):
        command.append("--enable_javascript")
    if settings.get("firefox"):
        command.append("--firefox")
    if settings.get("waittime"):
        command += ["--waittime", str(settings["waittime"])]
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


def one_page(url, args):
    #what a single page holds, found the way a scrape finds it: the element paths this script knows,
    #in a real browser. a walk of one page into a scratch index is exactly that, and needs no new mode.
    spare = os.path.join(index_folder(), "one-page-{0}.jsonl".format(os.getpid()))
    os.makedirs(os.path.dirname(spare), exist_ok=True)
    command = [sys.executable, MIRROR, "--index", spare, "--index-limit", "1", url]
    try:
        subprocess.run(command, text=True)
        held = read_index(spare)
    finally:
        if os.path.exists(spare):
            os.remove(spare)
    return held[0] if held else None
