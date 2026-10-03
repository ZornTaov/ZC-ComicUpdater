#lining a walk up against the files on disk: which saved file came from which page. anchors - a name or a
#size nothing else shares - pin positions exactly, and the stretches between them line up by order. it has
#to settle before a comic can be chaptered: missing pages are tolerated, unplaced files are not.
import os

from comiclib.chapters.index import alignment_path, fill_sizes, index_path, read_index, remember_cache, save_alignment
from comiclib.metadata import METADATA_FILE as metadata_file, now_stamp as time_stamp, read as read_metadata
from comiclib.metadata import write as write_metadata
from comiclib.pages import listing as folder_pages, page_key, sizes as file_sizes
from comiclib.standin import video_types


def recovered_files(folder, metadata=None):
    #pages the site itself no longer serves, which the reader found somewhere else and put in the folder
    #by hand. a walk cannot see them, so without being told, every tool here would call such a file a
    #stray and refuse to settle or to pack around it.
    metadata = read_metadata(folder) if metadata is None else metadata
    return {str(one.get("file")): one
            for one in ((metadata.get("history") or {}).get("recovered") or []) if one.get("file")}


def place_recovered(held, parcels, recovered):
    #a recovered page reads where it sits in the folder, which is where the reader put it: after the page
    #it follows. so it joins the chapter that page belongs to, rather than being appended somewhere tidy.
    known = {}
    for chapter, names in parcels:
        for name in names:
            known[name] = names
    placed = []
    for at, name in enumerate(held):
        if name not in recovered or name in known:
            continue
        before = next((held[back] for back in range(at - 1, -1, -1) if held[back] in known), None)
        names = known[before] if before else (parcels[0][1] if parcels else None)
        if names is None:
            continue
        names.insert(names.index(before) + 1 if before else 0, name)
        known[name] = names
        placed.append(name)
    return placed


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


def inside(held, low, high):
    #the positions of each value that fall strictly between two anchors
    return {value: [at for at in ats if low < at < high] for value, ats in held.items()}


def anchors_within(size_pages, size_files, name_pages, name_files, why):
    #the pages pinned to a file by a size, or failing that a name, that nothing else here shares, keeping only
    #those that agree with each other. why learns how each was pinned
    found = {}
    for at, to in unique_pairs(size_pages, size_files):
        found[at], why[at] = to, "size"
    #a name that agrees is no extra information, and a name that disagrees is the weaker of the two
    for at, to in unique_pairs(name_pages, name_files):
        if at not in found:
            found[at], why[at] = to, "name"
    return longest_run(sorted(found.items()))


def align(pages, files, folder=None, held=None):
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
        #held: each file's size, from one listing of the folder rather than a question per file
        held = file_sizes(folder) if held is None else held
        for at, page in enumerate(pages):
            if page.get("bytes"):
                size_pages.setdefault(page["bytes"], []).append(at)
        for at, name in enumerate(files):
            if name in held:
                size_files.setdefault(held[name], []).append(at)

    why = {}
    anchors = anchors_within(size_pages, size_files, name_pages, name_files, why)
    #a size two pages of a long comic happen to share - eight thousand jpegs of half a megabyte each make that
    #a certainty, not a fluke - anchors neither, and the stretch around them will not count out. between
    #two anchors already agreed, only a handful of pages and files are left, and among those the size
    #almost always points at one of each. so each stretch is asked again, on its own, until nothing more
    #is found; an anchor found there cannot cross the ones either side of it, which is what keeps it honest
    while True:
        more = []
        edges = [(-1, -1)] + anchors + [(len(pages), len(files))]
        for (page_from, file_from), (page_to, file_to) in zip(edges, edges[1:]):
            if page_to - page_from < 2 or file_to - file_from < 2:
                continue
            more += anchors_within(inside(size_pages, page_from, page_to), inside(size_files, file_from, file_to),
                                   inside(name_pages, page_from, page_to), inside(name_files, file_from, file_to),
                                   why)
        if not more:
            break
        anchors = sorted(anchors + more)

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


def verify(folder, files, pages, aligned, held=None):
    #every placement can be checked, not just the anchored ones: the file on disk should be as big as the
    #site says its image is. a size that differs is not proof of anything on its own - a comic that moved
    #host years ago serves re-encoded images that no longer match what was downloaded then. what does
    #prove something is the site's size matching a DIFFERENT file in this folder: that is a page sitting
    #where another page's file is, which is exactly what a wrong alignment looks like.
    held = file_sizes(folder) if held is None else held
    held_sizes = {}
    for name in files:
        if name in held:
            held_sizes.setdefault(held[name], []).append(name)
    agree, changed, conflict = 0, 0, []
    for page, name in zip(pages, aligned):
        if not name or not page.get("bytes"):
            continue
        if held.get(name) == page["bytes"]:
            agree += 1
        elif page["bytes"] in held_sizes:
            conflict.append((page["n"], name, held_sizes[page["bytes"]][:2]))
        else:
            changed += 1
    return agree, changed, conflict


def describe(folder, pages, files, aligned, how, anchors, trouble, rescued=(), recovered=None, held=None):
    matched = [name for name in aligned if name]
    recovered = recovered or {}
    spare = [name for name in files if name not in set(matched)]
    print("{0}".format(folder))
    ways = ", ".join("{0} by {1}".format(how.count(way), way) for way in ("size", "name", "order", "time")
                     if how.count(way))
    print("  {0} pages walked, {1} files held, {2} lined up ({3})".format(
        len(pages), len(files), len(matched), ways or "none"))
    if anchors:
        kinds = anchor_kinds(pages, files, anchors, folder)
        first, last = anchors[0], anchors[-1]
        print("  {0} anchor(s) agree ({1} by name, {2} by size), from page {3} ({4}) to page {5} ({6})".format(
            len(anchors), kinds["name"], kinds["size"], first[0] + 1, files[first[1]],
            last[0] + 1, files[last[1]]))
    elif "time" in how:
        print("  lined up by when each file was written, so the sizes below are the whole check")
    else:
        print("  no filename anchors: every page was renamed, so this rests on the counts matching")
    missing = [page for page, name in zip(pages, aligned) if not name]
    if missing:
        print("  {0} page(s) the comic has and this folder does not:".format(len(missing)))
        for page in missing[:12]:
            print("      page {0:<5} {1}".format(page["n"], page["url"]))
        if len(missing) > 12:
            print("      ... and {0} more".format(len(missing) - 12))
    if rescued:
        print("  {0} page(s) here that the site no longer serves, put back by hand:".format(len(rescued)))
        for name in rescued[:6]:
            print("      {0:<34} {1}".format(name[:34], (recovered[name].get("note") or "")[:52]))
        if len(rescued) > 6:
            print("      ... and {0} more".format(len(rescued) - 6))
    if spare:
        print("  {0} file(s) no page claims: {1}{2}".format(
            len(spare), spare[:4], "..." if len(spare) > 4 else ""))
        print("      a page the site has lost, that you found elsewhere, is not a stray: say so with "
              "chapters.py recovered {0} --file <name>".format(folder))
    #a page held as a video never matches the name of the image the site draws it with, and saying so
    #once is worth more than listing every one of them as a file that is not what the walk saw
    filmed = [name for name in aligned if name and video_types.search(name)]
    if filmed:
        print("  {0} page(s) are held as video rather than as a picture: {1}{2}".format(
            len(filmed), filmed[:4], "..." if len(filmed) > 4 else ""))
    named = [(page, name) for page, name in zip(pages, aligned)
             if name and page.get("src") and not video_types.search(name)]
    astray = [(page, name) for page, name in named
              if page_key(os.path.basename(page["src"].split('?')[0])) != page_key(name)]
    #only worth saying when most files ARE named after their image: then the few that are not stand out
    #as a page whose saved file is not its image - a scrape that caught a banner or an icon instead. on a
    #comic the site renamed wholesale, nothing matches and this says nothing.
    if named and len(astray) <= len(named) / 2:
        if astray:
            print("  {0} file(s) here are not the image the walk saw on that page:".format(len(astray)))
            for page, name in astray[:6]:
                print("      page {0:<5} {1:<26} site serves {2}".format(
                    page["n"], name[:26], os.path.basename(page["src"].split('?')[0])))
            if len(astray) > 6:
                print("      ... and {0} more".format(len(astray) - 6))
            print("      chapters.py refetch {0} --page <n> --as-named puts one right.".format(folder))
    agree, changed, conflict = verify(folder, files, pages, aligned, held)
    #a size says where a page is only where sizes say anything at all. a site that re-exported its whole
    #archive - every image re-encoded at four fifths the size - leaves every one of them different, and then
    #a size that happens to match some other file among thousands is a coincidence rather than a page in
    #the wrong place. so they are still reported, and they stop counting as a fault.
    sizes_tell = agree >= changed
    print("  checked against the site's own sizes: {0} match exactly, {1} differ (re-uploaded since, "
          "and their size is held by no other file here), {2} land on another page's file".format(
              agree, changed, len(conflict)))
    for n, name, others in conflict[:8]:
        print("      page {0:<5} placed at {1:<26} but its size belongs to {2}".format(n, name[:26], others))
    if len(conflict) > 8:
        print("      ... and {0} more".format(len(conflict) - 8))
    if conflict and not sizes_tell:
        print("      only {0} of {1} sizes match the site at all, so these are coincidences among "
              "thousands of files rather than pages out of place.".format(agree, agree + changed))
    for problem in trouble:
        print("  UNRESOLVED {0}: {1}".format(problem["where"], problem["detail"]))
    #what chaptering needs is that every file is placed. a page the comic has and this folder does not
    #leaves a gap in the reading, but the files either side of it are still placed correctly.
    settled = not trouble and not spare and not (conflict and sizes_tell)
    if settled and missing:
        print("  settled: every file is placed. The {0} page(s) above are missing from this folder, "
              "not misplaced.".format(len(missing)))
    elif settled:
        print("  settled: every page has a file and every file has a page")
    else:
        print("  NOT settled: fix the above, or align by hand, before chaptering")
    return settled


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


def by_written_order(folder, pages, files):
    #for a comic this scraper downloaded itself, in one pass, without numbering the files: the order the
    #files were written IS the order the pages were published, because that is the order they were
    #fetched. it needs no names and no sizes, which is what makes it work on a site that serves
    #jan.png for one page and 99002.jpg for the next.
    if len(files) != len(pages):
        print("ERROR: {0} file(s) here but {1} page(s) walked. Lining up by when files were written "
              "needs one of each, so this comic needs the usual alignment.".format(len(files), len(pages)))
        return None, None
    stamped = []
    for name in files:
        try:
            stamped.append((os.path.getmtime(os.path.join(folder, name)), name))
        except OSError as error:
            print("ERROR: could not read when {0} was written: {1}".format(name, error))
            return None, None
    stamped.sort()
    ties = sum(1 for one, next_one in zip(stamped, stamped[1:]) if one[0] == next_one[0])
    if ties:
        print("  {0} file(s) share a write time with the next, so their order between themselves is "
              "guesswork; the sizes below say whether it landed right.".format(ties))
    return [name for _, name in stamped], ["time"] * len(pages)


def do_align(folder, args):
    cache = index_path(folder, args.root, args)
    if not os.path.exists(cache):
        print("ERROR: no index for {0} yet. Run: chapters.py index {1}".format(folder, folder))
        return 2
    pages = read_index(cache)
    #a page the site has lost belongs to no walked page, so it takes no part in the lining up: left in,
    #it would leave a stretch with one more file than pages and nothing would settle
    recovered = recovered_files(folder)
    #videos count here, and only here: a page held as one is a page this folder has, and leaving it out
    #made it read as a page gone missing and the file itself as something nothing claims
    held = folder_pages(folder, others=True)
    files = [name for name in held if name not in recovered]
    rescued = [name for name in held if name in recovered]
    #every file's size from one listing, shared by the lining up and the check after it: asking file by
    #file was most of the time a comic of thousands took, run against a library on a network share
    print("  reading the size of every file ...", flush=True)
    sizes = file_sizes(folder)
    fill_sizes(cache, pages)
    if args.by_time:
        aligned, how = by_written_order(folder, pages, files)
        if aligned is None:
            return 2
        anchors, trouble = [], []
    else:
        aligned, how, anchors, trouble = align(pages, files, folder, sizes)
    settled = describe(folder, pages, files, aligned, how, anchors, trouble, rescued, recovered, sizes)
    where = save_alignment(alignment_path(cache), folder, pages, aligned, how, settled)
    remember_cache(folder, cache)
    print("  written to {0}".format(where))
    if settled:
        save_gaps(folder, pages, aligned)
    return 0 if settled else 1
