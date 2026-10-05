#one archive per chapter, written from the folder, and the single archive written afresh. every page goes
#in exactly one chapter, and each archive is checked against the folder before anything is given up.
import os
import posixpath
import re
import shutil
import zipfile

from comiclib import cbz
from comiclib.cbz import shelf
from comiclib.chapters.align import place_recovered, recovered_files
from comiclib.chapters.index import joined_pages
from comiclib.metadata import METADATA_FILE as metadata_file, now_stamp as time_stamp, read as read_metadata
from comiclib.metadata import write as write_metadata
from comiclib.pages import PAGE_TYPES, SET_ASIDE, listing as folder_pages, sizes as file_sizes
from comiclib.standin import held_otherwise


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
    if cbz:
        full = cbz if os.path.isabs(cbz) or not root else os.path.join(root, cbz.replace('/', os.sep))
    else:
        #a comic adopted or uploaded with no archive named is filed by the same rule a scrape files its single
        #archive by: under Uncompressed, so on the CBZs shelf beside it. going straight to a folder beside the
        #pages put a comic's chapters among the loose pages, where no reader looks for them
        tree, found = shelf(folder)
        if not found:
            return os.path.abspath(folder) + "_chapters"
        full = os.path.join(found, os.path.relpath(os.path.abspath(folder), tree)) + ".cbz"
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
    parcels, otherwise = [], []
    for chapter in chapters:
        names = []
        for n in range(chapter["start_page"], chapter["end_page"] + 1):
            name = (by_page.get(n) or {}).get("file")
            if not name:
                continue
            #a page held as a video, as flash, or as a note saying where it lives now stays in the
            #parcel: the packing puts a stand-in in the archive where it belongs, saying where to go
            if held_otherwise(folder, name):
                otherwise.append(name)
            names.append(name)
        parcels.append((chapter, names))
    if otherwise:
        print("  {0} page(s) no reader can show, which the archives get a stand-in for: {1}{2}".format(
            len(otherwise), otherwise[:3], "..." if len(otherwise) > 3 else ""))
    #a page the site no longer serves cannot be in `pages`, because the walk never saw it. it still has
    #to end up in a chapter, or packing would refuse to write around it. that includes one held as a
    #video or a note: put back by hand, it is as much a page as any picture, and leaving it out of this
    #listing left it in no chapter at all while the check for strays could still see it.
    held = folder_pages(folder, others=True)
    recovered = recovered_files(folder)
    if parcels and recovered:
        placed = place_recovered(held, parcels, recovered)
        if placed:
            print("  {0} page(s) the site no longer serves, put back by hand, kept where they read: "
                  "{1}{2}".format(len(placed), placed[:3], "..." if len(placed) > 3 else ""))
    #pages saved since the chapters were worked out belong to the chapter still being published, which is
    #the last one. they are added in the order they were saved, which is the order they came out.
    if parcels:
        known = {name for _, names in parcels for name in names}
        last_known = max((at for at, name in enumerate(held) if name in known), default=-1)
        fresh = [name for name in held[last_known + 1:] if name not in known]
        if fresh:
            parcels[-1][1].extend(fresh)
            print("  {0} page(s) saved since the chapters were worked out join chapter {1}".format(
                len(fresh), parcels[-1][0]["number"]))
    return parcels


def already_packed(path, names, folder, sizes=None):
    #an archive only needs writing again if what it holds is not what it should hold
    if not os.path.exists(path):
        return False
    try:
        held = cbz.held(path)
        wanted = cbz.expected(folder, names, sizes)
    except (OSError, zipfile.BadZipFile):
        return False
    held.pop("ComicInfo.xml", None)
    return held == wanted


def pack(folder, args):
    metadata = read_metadata(folder)
    if (metadata.get("settings") or {}).get("cbz") is False and not args.force:
        print("{0} is set to keep no archives (cbz is off in its settings), so nothing was written. Turn "
              "that on, or pass --force to write them anyway.".format(folder))
        return 0
    chapters = (metadata.get("chapters") or {}).get("list")
    if not chapters:
        print("ERROR: no chapters worked out for {0} yet. Run: chapters.py chapters {0} --archive ...".format(folder))
        return 2
    #a comic cut by size may never have been walked, its filenames saying which page is which instead
    pages = joined_pages(folder, args, numbered=(metadata.get("chapters") or {}).get("source") == "every")
    if pages is None:
        return 2
    shelf = chapter_folder(folder, metadata, args.root, args.cbz_folder)
    parcels = chapter_contents(folder, chapters, pages)
    held = {name for _, names in parcels for name in names}
    print("  listing what is in the comic's folder ...", flush=True)
    on_disk = set(folder_pages(folder, others=True))
    astray = sorted(on_disk - held)
    if astray:
        print("ERROR: {0} file(s) belong to no chapter, so nothing was written: {1}{2}".format(
            len(astray), astray[:5], "..." if len(astray) > 5 else ""))
        return 1

    print("{0}: {1} chapter(s) into {2}".format(folder, len(parcels), shelf))
    print("  looking at what the archives already hold ...", flush=True)
    sizes = file_sizes(folder)
    todo = []
    for at, (chapter, names) in enumerate(parcels, 1):
        if not already_packed(os.path.join(shelf, chapter_file(folder, chapter)), names, folder, sizes):
            todo.append((chapter, names))
        if at % 10 == 0 and at < len(parcels):
            print("    looked at {0} of {1}".format(at, len(parcels)), flush=True)
    print("  {0} to write, {1} already as they should be".format(len(todo), len(parcels) - len(todo)))
    for chapter, names in parcels[:100]:
        mark = "write" if (chapter, names) in todo else "keep "
        print("  {0} c{1:03d} {2:<44} {3:>4} page(s)  {4}".format(
            mark, chapter["number"], tidy_name(chapter["label"])[:44], len(names),
            chapter_file(folder, chapter)[:60]))
    if args.dry_run:
        print("Nothing was written. Run it again without --dry-run.")
        return 0

    written = 0
    for chapter, names in todo:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        print("  writing {0} ({1} page(s)) ...".format(os.path.basename(path), len(names)), flush=True)
        #a page no reader can show goes in as a page saying where the real one is, named so it falls where
        #the page belongs - the same stand-in the single archive of a comic not in chapters gets
        cbz.write(path, folder, names, first=[("ComicInfo.xml", comic_info(folder, chapter, len(parcels), names))])
        written += 1
        print("  wrote {0} ({1} page(s))".format(os.path.basename(path), len(names)), flush=True)
    print("Wrote {0} chapter archive(s).".format(written))

    kept = verify_chapters(folder, shelf, parcels)
    if kept is not True:
        return 1
    metadata = read_metadata(folder)
    block = metadata.setdefault("chapters", {})
    block["folder"] = os.path.relpath(shelf, args.root).replace(os.sep, '/') if args.root else shelf
    block["packed"] = time_stamp()
    #nothing is turned off here: a comic that has chapters is one mirror_base leaves alone, and whether it
    #has archives at all is the one cbz setting, the same switch as for a comic with no chapters
    write_metadata(folder, metadata)

    if args.replace:
        return drop_single(folder, metadata, args, shelf)
    return 0


def verify_chapters(folder, shelf, parcels):
    #every page has to be in exactly one chapter archive, at the size it is on disk, before the single
    #archive that holds them all can be given up
    seen, trouble = {}, []
    for chapter, names in parcels:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        try:
            held = cbz.held(path)
        except (OSError, zipfile.BadZipFile) as error:
            trouble.append("c{0:03d}: {1}".format(chapter["number"], error))
            continue
        for name in names:
            #a page held as something no reader can show is in the archive as its stand-in, so that is
            #what has to be there and at the size the drawing comes to
            (entry, size), = cbz.expected(folder, [name]).items()
            if held.get(entry) != size:
                trouble.append("c{0:03d}: {1} is {2} in the archive, {3} on disk".format(
                    chapter["number"], entry, held.get(entry), size))
            if name in seen:
                trouble.append("{0} is in both c{1:03d} and c{2:03d}".format(name, seen[name], chapter["number"]))
            seen[name] = chapter["number"]
    missing = sorted(set(folder_pages(folder, others=True)) - set(seen))
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


def keep_extras(full, folder, keep_in):
    #a single archive another scraper made can hold more than the pages: a copy of the script that made it,
    #a readme. the chapter archives are checked against the folder, so anything the folder never had would
    #go with the single archive. it is written out beside the chapter archives first, where a reader skips
    #it and it stays with its comic. False, with the archive left alone, when that cannot be done cleanly
    #what the reader took out of the comic and set aside - an older version of a page, a commentary picture -
    #is kept already, in the folder's ".set aside", and is no more an extra than a page is
    aside = os.path.join(folder, SET_ASIDE)
    places = [folder] + ([aside] if os.path.isdir(aside) else [])
    on_disk = {name for place in places for name in os.listdir(place)}
    #a page renamed since the archive was made - given back the site's own name - is in the folder under
    #another name, so a picture whose name is not here is only an extra if no page here has its bytes. the
    #size says which pages could be, and the bytes are compared only for those
    by_size = {}
    for place in places:
        for name in os.listdir(place):
            try:
                by_size.setdefault(os.path.getsize(os.path.join(place, name)), []).append(os.path.join(place, name))
            except OSError:
                continue

    def renamed_page(zf, info):
        if not PAGE_TYPES.search(info.filename):
            return False
        candidates = by_size.get(info.file_size) or []
        if not candidates:
            return False
        held = zf.read(info)
        for path in candidates:
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    if f.read() == held:
                        return True
        return False

    try:
        with zipfile.ZipFile(full) as zf:
            extras = [info for info in zf.infolist()
                      if not info.is_dir() and posixpath.basename(info.filename) not in on_disk
                      and not renamed_page(zf, info)]
            names = [posixpath.basename(info.filename) for info in extras]
            clash = sorted({name for name in names
                            if names.count(name) > 1 or os.path.exists(os.path.join(keep_in, name))})
            if clash:
                print("{0} holds {1} that the folder does not, and {2} would not be the only file of that "
                      "name in {3}, so the archive was kept. Take what you want out of it by hand.".format(
                          full, ", ".join(names[:5]), ", ".join(clash[:3]), keep_in))
                return False
            for info, name in zip(extras, names):
                target = os.path.join(keep_in, name)
                with zf.open(info) as source, open(target + ".writing", "wb") as out:
                    shutil.copyfileobj(source, out)
                os.replace(target + ".writing", target)
                print("Kept {0} from it, which no page is: now {1}".format(info.filename, target))
    except (OSError, zipfile.BadZipFile) as error:
        print("Could not look inside {0} ({1}), so it was kept.".format(full, error))
        return False
    return True


def drop_single(folder, metadata, args, shelf=None):
    cbz = (metadata.get("settings") or {}).get("cbz_path")
    if not cbz:
        return 0
    full = cbz if os.path.isabs(cbz) else os.path.join(args.root or os.path.dirname(folder),
                                                       cbz.replace('/', os.sep))
    if not os.path.exists(full):
        return 0
    if not keep_extras(full, folder, shelf or os.path.dirname(full)):
        return 1
    size = os.path.getsize(full)
    os.remove(full)
    print("Removed {0} ({1:.0f} MB); the chapter archives hold every page it held.".format(full, size / 1e6))
    return 0


def repack(folder, args):
    #a zip cannot replace an entry in place, so the archive is written afresh beside the old one and
    #swapped in only once it is complete and holds every page
    archive = args.cbz
    if not archive:
        metadata = read_metadata(folder)
        archive = (metadata.get("settings") or {}).get("cbz_path")
        if archive and args.root and not os.path.isabs(archive):
            archive = os.path.join(args.root, archive)
    if not archive or not os.path.exists(archive):
        print("No archive found to repack; pass --cbz with its path.")
        return 1
    on_disk = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    #the metadata last, as a scrape writes it, so a later scrape adding to this archive can reclaim it
    names = [f for f in on_disk if f != metadata_file] + [f for f in on_disk if f == metadata_file]
    with zipfile.ZipFile(archive) as zf:
        prefix = cbz.archive_prefix(zf, folder)
    spare = archive + ".repacking"
    print("Repacking {0} ({1} file(s)) ...".format(archive, len(names)))
    #through the same packing as every other archive, so a page no reader can show goes in as its
    #stand-in here too, rather than as a video no reader can open
    cbz.write(spare, folder, names, prefix)
    wanted = {prefix + entry: size for entry, size in cbz.expected(folder, names).items()}
    if cbz.held(spare) != wanted:
        os.remove(spare)
        print("ERROR: the new archive does not hold every file as it is on disk, so the old one was left "
              "alone.")
        return 1
    shutil.move(spare, archive)
    print("  {0} now holds every page as it is on disk.".format(archive))
    return 0
