#work on a comic's pages themselves: fetching one again, numbering them all, putting in one the comic's own
#links skip, and noting one found somewhere else. each keeps the index and the alignment in step, since
#they are what say which file is which page.
import json
import os
import re

import requests

from comiclib.chapters.align import do_align
from comiclib.chapters.index import alignment_path, index_path, joined_pages, one_page, read_index
from comiclib.chapters.links import page_at, same_page
from comiclib.chapters.packing import repack
from comiclib.metadata import now_stamp as time_stamp, read as read_metadata, write as write_metadata, write_json
from comiclib.pages import numbered_name, page_number, reading_order, saved_name, sort_key, type_from_bytes


def refetch(folder, args):
    #the copies in a library that came from somewhere else are often compressed harder than what the site
    #serves. this fetches those pages again under the names they already have, so nothing else has to change
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    only = set()
    if args.page:
        try:
            only = {int(bit) for bit in str(args.page).replace(',', ' ').split()}
        except ValueError:
            print("ERROR: --page takes page numbers, such as --page 1 or --page 1,5,9.")
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
        if only:
            if page["n"] in only:
                wanted.append((page, held))
        elif args.all or (page["bytes"] and held != page["bytes"]):
            wanted.append((page, held))
    if only:
        missed = only - {page["n"] for page, _ in wanted}
        if missed:
            print("ERROR: no page {0} with a file and a known image here.".format(sorted(missed)))
            return 2
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
    done, kept, failed, renamed = 0, 0, [], []
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
        if not args.as_named and len(fresh) <= held:
            kept += 1
            continue
        if args.as_named:
            #the file here is not this page's image at all - a scrape that matched the site's banner or an
            #author icon instead of the comic. the right copy belongs under the right name, so the wrong
            #one goes rather than being overwritten and keeping a name that was never true.
            #the name the site gives the image, the way a scrape names it
            want = saved_name(page["src"], answer.headers, fresh)
            number = re.match(r'^(\d{1,6})_', page["file"])
            if number:
                want = "{0}_{1}".format(number.group(1), want)
            if want != page["file"]:
                if os.path.exists(os.path.join(folder, want)):
                    failed.append((page["n"], "{0} is already here".format(want)))
                    continue
                renamed.append((page["n"], page["file"], want))
                path = os.path.join(folder, want)
        spare = path + ".fetching"
        with open(spare, 'wb') as f:
            f.write(fresh)
        os.replace(spare, path)
        for at, was, now in renamed[-1:]:
            if at == page["n"] and os.path.exists(os.path.join(folder, was)):
                os.remove(os.path.join(folder, was))
                print("  page {0}: {1} was not this page; saved {2} instead".format(at, was, now))
        done += 1
        if done % 25 == 0:
            print("  {0} of {1} replaced".format(done, len(wanted)))
    if renamed:
        #the alignment names the file for each page, so it has to learn the new ones or everything after
        #this looks at a file that is no longer there
        alignment = alignment_path(index_path(folder, args.root, args))
        saved = json.load(open(alignment, encoding='utf-8'))
        fresh_names = {at: now for at, _, now in renamed}
        for page in saved["pages"]:
            if page["n"] in fresh_names:
                page["file"] = fresh_names[page["n"]]
        write_json(alignment, saved, indent=1)
        print("  {0} name(s) put right in the alignment too.".format(len(renamed)))
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


def renumber(folder, args):
    #a comic scraped without --prefix keeps the site's own names, and a site that calls one page jan.png
    #and the next 99002.jpg reads in no order at all. the alignment is the only thing that knows which
    #file is which page, so the numbers come from there and from nothing else.
    cache = index_path(folder, args.root, args)
    alignment = alignment_path(cache)
    if not os.path.exists(alignment):
        print("ERROR: {0} has not been lined up yet. Run: chapters.py index {0}".format(folder))
        return 2
    saved = json.load(open(alignment, encoding='utf-8'))
    if not saved.get("settled") and not args.force:
        print("ERROR: this comic's alignment is not settled, so which file is which page is not certain "
              "and numbering them would write that uncertainty into their names. Sort the alignment out "
              "first, or pass --force if you are sure.")
        return 2
    held = set(os.listdir(folder))
    original = getattr(args, "original", False)
    filed = [page for page in saved["pages"] if page.get("file")]
    named = {}
    if original or getattr(args, "site_names", False):
        named = {page["n"]: site_name(folder, page["src"], page["file"]) for page in filed if page.get("src")}
    #a page keeps the very name the site gave it - the name that finds it again when searching for it -
    #unless those names would not read in the comic's order, or two pages share one. then every page
    #carries its number in front of it, which keeps both the name and the order
    numbering = True
    if original:
        names = [named.get(page["n"]) for page in filed]
        if not all(names):
            print("{0} page(s) have no image of the site's to be named after, so every page is numbered.".format(
                sum(1 for name in names if not name)))
        elif len(set(names)) < len(names):
            print("The site uses {0} for more than one page, so every page is numbered.".format(
                sorted({name for name in names if names.count(name) > 1})[0]))
        elif reading_order(folder, names) != names or sorted(names, key=sort_key) != names:
            wrong = next(at for at, (one, other) in enumerate(zip(names, sorted(names, key=sort_key)))
                         if one != other)
            print("The site's names would not read in order - {0} would come before {1} - so every page "
                  "is numbered.".format(sorted(names, key=sort_key)[wrong], names[wrong]))
        else:
            numbering = False
            print("The site's own names read in the comic's order, so each page keeps its name as it is.")
    moves, already = [], 0
    for page in filed:
        name = page["file"]
        if original and not numbering:
            want = named[page["n"]]
        elif page["n"] in named:
            #the number in front of the site's own name for the image, which is what a scrape with
            #--prefix writes: so a comic first saved by some other tool reads the same as what it gains next
            want = "{0:04d}_{1}".format(page["n"], named[page["n"]])
        elif re.match(r'^\d+\.\w+$', name):
            #a page with no image of the site's, saved by another tool as a bare count: its number is all
            #there is to say about it, and its own bytes what kind of picture it is
            want = "{0:04d}{1}".format(page["n"], os.path.splitext(site_name(folder, name, name))[1])
        else:
            want = numbered_name(page["n"], name)
        if want == name:
            already += 1
        else:
            moves.append((name, want))
    if not moves:
        print("{0}: all {1} file(s) already carry their page number.".format(folder, already))
        return 0
    #every page must want a name of its own, and must not want one that belongs to a file staying put
    wanted = [want for _, want in moves]
    twice = sorted({want for want in wanted if wanted.count(want) > 1})
    staying = held - {name for name, _ in moves}
    taken = sorted(want for want in wanted if want in staying)
    if twice or taken:
        print("ERROR: these names would collide, so nothing was renamed:")
        for want in (twice + taken)[:10]:
            print("      {0}".format(want))
        return 2
    print("{0}: {1} file(s) to {2}, {3} already named so".format(
        folder, len(moves), "number" if numbering else "rename", already))
    for name, want in moves[:4]:
        print("      {0}  ->  {1}".format(name[:44], want[:44]))
    if len(moves) > 4:
        print("      ... and {0} more".format(len(moves) - 4))
    if args.dry_run:
        print("  nothing was renamed. Run it again without --dry-run once this looks right.")
        return 0
    #moved through names nothing else can hold, so a file never lands on one still waiting to be moved
    stepped = []
    try:
        for at, (name, want) in enumerate(moves):
            step = os.path.join(folder, "{0}.renaming{1}".format(want, at))
            os.rename(os.path.join(folder, name), step)
            stepped.append((name, step, want))
        for _, step, want in stepped:
            os.rename(step, os.path.join(folder, want))
    except OSError as error:
        print("ERROR: renaming stopped: {0}".format(error))
        print("  putting back the {0} file(s) that had moved ...".format(len(stepped)))
        for name, step, _ in stepped:
            if os.path.exists(step):
                os.rename(step, os.path.join(folder, name))
        print("  nothing was renamed in the end.")
        return 2
    print("  {0} file(s) renamed.".format(len(moves)))
    renamed = dict(moves)
    for page in saved["pages"]:
        if page.get("file") in renamed:
            page["file"] = renamed[page["file"]]
    write_json(alignment, saved, indent=1)
    metadata = read_metadata(folder)
    if metadata:
        settings = metadata.setdefault("settings", {})
        #a page set by hand is remembered by its file, which has just been renamed under it
        for made in (metadata.get("history") or {}).get("hand_made") or []:
            if made.get("file") in renamed:
                made["file"] = renamed[made["file"]]
        if numbering:
            if not settings.get("prefix"):
                settings["prefix"] = True
                print("  this comic now saves new pages with their number too (prefix is on).")
            #and numbers them on from the page it resumes on, which a run re-saves under the very name it
            #has just been given. a count kept by another tool, from 0, would number every new page wrong
            resumes = next((page["n"] for page in filed
                            if settings.get("url") and same_page(page["url"]) == same_page(settings["url"])),
                           filed[-1]["n"] if filed else None)
            if resumes and settings.get("increment") != resumes:
                print("  it resumes on page {0}, so new pages are numbered on from there (increment {1} -> "
                      "{0}).".format(resumes, settings.get("increment")))
                settings["increment"] = resumes
        write_metadata(folder, metadata)
    print("  the archive still holds the old names: chapters.py repack {0} --root <library>, or pack "
          "for a chaptered comic.".format(folder))
    return 0


def site_name(folder, src, name):
    #what the site calls a page's image, with the extension the file's own bytes call for. another tool can
    #have saved a jpg as 0042.png, and the site can since have swapped a gif for a jpg under a new name; a
    #reader goes by the extension to know how to open an entry, so the bytes on disk decide it, not the site
    want = saved_name(src)
    try:
        with open(os.path.join(folder, name), 'rb') as f:
            kind = type_from_bytes(f.read(12))
    except OSError:
        kind = None
    stem, ending = os.path.splitext(want)
    if kind and ending.lower().lstrip(".").replace("jpeg", "jpg") != kind:
        want = "{0}.{1}".format(stem, kind)
    return want


def shift_up(folder, pages, at):
    #every page from here on moves one place along, so the new page has a place of its own. renamed from
    #the back, so a file never lands on one that has not moved yet.
    moved = []
    for page in reversed(pages):
        if page["n"] < at or not page.get("file"):
            continue
        want = numbered_name(page["n"] + 1, page["file"])
        if want == page["file"]:
            continue
        os.rename(os.path.join(folder, page["file"]), os.path.join(folder, want))
        moved.append((page["n"], page["file"], want))
    return moved


def insert_page(folder, args):
    #a page the comic's own next links skip - one the archive lists and the navigation walks straight
    #past - can be reached by nothing that follows the comic. so it is put in by hand: the
    #page is read, its image saved, and everything after it moves along one so the order still reads true.
    if not args.url or not args.after:
        print("ERROR: say which page to put in with --url, and which page it follows with --after.")
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    by_file = [page for page in pages if page.get("file")]
    if not by_file or not all(page_number(page["file"]) is not None for page in by_file):
        print("ERROR: this comic's files do not carry their page numbers, so there is nowhere to put one "
              "in without guessing. Run: chapters.py renumber {0}".format(folder))
        return 2
    after = page_at(pages, args.after) if not str(args.after).strip().isdigit() else int(args.after)
    if not after or after > len(pages):
        print("ERROR: {0} is not a page of this comic.".format(args.after))
        return 2
    if page_at(pages, args.url):
        print("This comic already holds {0}, as page {1}.".format(args.url, page_at(pages, args.url)))
        return 0
    at = after + 1
    print("{0} goes in at page {1}, after {2}".format(args.url, at, pages[after - 1]["url"]))
    found = one_page(args.url, args)
    if not found or not found.get("src"):
        print("ERROR: no comic image was found on {0}. Check it in the browser, or add an element path "
              "for this site.".format(args.url))
        return 2
    #fetched before anything is moved, so a page that cannot be had leaves the comic exactly as it was
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        answer = session.get(found["src"], timeout=120)
        answer.raise_for_status()
    except requests.RequestException as error:
        print("ERROR: could not fetch {0}: {1}".format(found["src"], error))
        return 2
    print("  {0} bytes from {1}".format(len(answer.content), found["src"]))
    #the name a scrape would give this image, worked out here rather than taken from the walk's record, so
    #putting a page in does not depend on that record being right about it
    name = "{0:04d}_{1}".format(at, saved_name(found["src"], answer.headers, answer.content))
    if args.dry_run:
        print("  it would be saved as {0}, and {1} page(s) after it would move along one. Nothing was "
              "changed.".format(name, len(pages) - after))
        return 0

    moved = shift_up(folder, pages, at)
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(answer.content)
    print("  saved {0}; {1} page(s) after it moved along one".format(name, len(moved)))

    #the index is what says the comic's order, so it learns the page too: no walk can reach it, and a
    #walk that could would have found it already
    cache = index_path(folder, args.root, args)
    lines = read_index(cache)
    fresh = {"n": at, "url": args.url, "src": found["src"], "file": name,
             "title": found.get("title"), "bytes": len(answer.content)}
    out = [line for line in lines if line["n"] < at]
    out.append(fresh)
    for line in lines:
        if line["n"] >= at:
            out.append(dict(line, n=line["n"] + 1,
                            file=numbered_name(line["n"] + 1, line["file"])
                            if line.get("file") else None))
    spare = cache + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        for line in out:
            f.write(json.dumps(line) + chr(10))
    os.replace(spare, cache)
    print("  the walk's own record now holds {0} page(s)".format(len(out)))

    metadata = read_metadata(folder)
    if metadata:
        history = metadata.setdefault("history", {})
        history["inserted"] = (history.get("inserted") or []) + [
            {"page": at, "url": args.url, "file": name, "at": time_stamp(),
             "note": args.note or "the comic's own next links skip this page, so it was put in by hand"}]
        #a chapter starting after this page starts one page later than it did. the page it starts AT has
        #not changed, only its number, so the numbers are moved and nothing is re-read.
        block = metadata.get("chapters") or {}
        shifted = [chapter for chapter in (block.get("list") or []) if chapter.get("start_page", 0) >= at]
        for chapter in shifted:
            chapter["start_page"] += 1
        for chapter in block.get("list") or []:
            if chapter.get("end_page", 0) >= at:
                chapter["end_page"] += 1
                chapter["pages"] = chapter["end_page"] - chapter["start_page"] + 1
        if block.get("list"):
            #the files those chapters hold are named after their page numbers, so the ones past here have
            #all been renamed and their archives no longer hold what they should
            print("  {0} chapter(s) start later than they did; their archives need writing again: "
                  "chapters.py pack {1}".format(len(shifted), folder))
        write_metadata(folder, metadata)
    print()
    return do_align(folder, args)


def mark_recovered(folder, args):
    #a page the site has lost, found somewhere else and put in the folder by hand. saying so once keeps
    #every later run from calling it a stray, and keeps it in the chapter it reads in when packing.
    metadata = read_metadata(folder)
    if not metadata:
        print("ERROR: no metadata in {0}.".format(folder))
        return 2
    history = metadata.setdefault("history", {})
    held = list(history.get("recovered") or [])
    if not args.file and not args.clear:
        print("{0}: {1} page(s) put back by hand".format(folder, len(held)))
        for one in held:
            there = os.path.exists(os.path.join(folder, str(one.get("file"))))
            print("  {0:<36} {1}{2}".format(str(one.get("file"))[:36], (one.get("note") or "")[:46],
                                            "" if there else "   (no longer in this folder)"))
        if not held:
            print("  none. Use --file <name> once you have put one there.")
        return 0
    if args.clear:
        print("forgotten: all {0}".format(len(held)))
        held = []
    if args.file:
        name = os.path.basename(str(args.file))
        if not args.forget and not os.path.exists(os.path.join(folder, name)):
            print("ERROR: {0} is not in {1}. Put the page there first, named so it sorts where it "
                  "reads.".format(name, folder))
            return 2
        held = [one for one in held if one.get("file") != name]
        if args.forget:
            print("forgotten: {0}".format(name))
        else:
            held.append({"file": name, "note": args.note or "the site no longer serves this page",
                         "at": time_stamp()})
            print("noted: {0} is a page this comic has and the site does not".format(name))
    if held:
        history["recovered"] = held
    else:
        history.pop("recovered", None)
    write_metadata(folder, metadata)
    if not args.forget and not args.clear:
        print("  line the comic up again so it settles around it: chapters.py align {0}".format(folder))
    return 0
