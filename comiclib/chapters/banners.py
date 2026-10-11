#a chapter's banner - the picture its site shows over it on the chapter list - saved beside the chapter's
#archive under the archive's own name, which is where a reader looks for a book's cover. one already there,
#whoever put it there, is left alone: a cover chosen in a reader is not the chapter list's to replace.
import os
import posixpath
import urllib.parse

from comiclib import comicinfo
from comiclib.chapters.packing import chapter_file, chapter_folder
from comiclib.download import fetch
from comiclib.exits import MirrorError
from comiclib.metadata import read as read_metadata

#what a cover beside an archive can be called, as readers look for one
ENDINGS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
#a picture's ending from its first bytes, for an address that does not say - chapter.php?banner=3
KINDS = ((b"\x89PNG", ".png"), (b"\xff\xd8", ".jpg"), (b"GIF8", ".gif"), (b"RIFF", ".webp"))


def beside(archive):
    #the picture already beside an archive under its name, if there is one
    stem = os.path.splitext(archive)[0]
    return next((stem + ending for ending in ENDINGS if os.path.exists(stem + ending)), None)


def ending_of(url, body):
    said = posixpath.splitext(urllib.parse.urlsplit(url).path)[1].lower()
    if said in ENDINGS:
        return ".jpg" if said == ".jpeg" else said
    return next((ending for start, ending in KINDS if body.startswith(start)), None)


def save_banners(folder, chapters, shelf, referer=None, dry_run=False):
    #each chapter's banner beside its archive, for the chapters that have both. answers how many were saved
    saved, failed, kept = 0, 0, 0
    for chapter in chapters:
        if not chapter.get("image"):
            continue
        archive = os.path.join(shelf, chapter_file(folder, chapter))
        if not os.path.exists(archive):
            continue
        if beside(archive):
            kept += 1
            continue
        if dry_run:
            print("  would save the banner for c{0:03d} from {1}".format(chapter["number"], chapter["image"]))
            saved += 1
            continue
        try:
            body = fetch(chapter["image"], referer=referer).content
        except MirrorError as error:
            print("  no banner for c{0:03d}: {1}".format(chapter["number"], error))
            failed += 1
            continue
        ending = ending_of(chapter["image"], body)
        #an error page or a placeholder served under a picture's address is not a cover. a picture says its
        #size in its first bytes, and a page of html never does
        if ending is None or comicinfo.measure(lambda n: body[:n]) is None:
            print("  no banner for c{0:03d}: {1} is not a picture".format(chapter["number"], chapter["image"]))
            failed += 1
            continue
        path = os.path.splitext(archive)[0] + ending
        try:
            with open(path + ".writing", "wb") as f:
                f.write(body)
            os.replace(path + ".writing", path)
        except OSError as error:
            print("  could not save the banner for c{0:03d} beside its archive: {1}".format(chapter["number"], error))
            failed += 1
            continue
        saved += 1
    if saved or failed:
        print("{0} {1} chapter banner(s) beside the archives{2}{3}.".format(
            "Would save" if dry_run else "Saved", saved,
            ", {0} could not be".format(failed) if failed else "",
            ", {0} already had a cover".format(kept) if kept else ""))
    return saved, failed


def covers(folder, args):
    #chapters.py covers: the banners of a comic already packed, with nothing packed again
    metadata = read_metadata(folder)
    block = metadata.get("chapters") or {}
    chapters = block.get("list") or []
    if not chapters:
        print("{0} has no chapters worked out, so there are no banners to save. Run chapters.py chapters "
              "first.".format(folder))
        return 1
    if not any(chapter.get("image") for chapter in chapters):
        print("None of {0}'s chapters has a banner recorded. Read its chapter list again to record them: "
              "chapters.py chapters {0} --save{1}".format(
                  folder, "" if block.get("source_url") else " --archive <its chapter list page>"))
        return 1
    shelf = chapter_folder(folder, metadata, args.root, args.cbz_folder)
    save_banners(folder, chapters, shelf, referer=block.get("source_url"), dry_run=args.dry_run)
    return 0
