#works out which saved file came from which page of a comic, by walking the comic without downloading
#anything and lining that walk up against what is already on disk. the walk is the slow part and its
#result is cached; the alignment is what everything about chapters is later built on. #V 1.0
#
#this is the command; the work is in comiclib.chapters, one module for each part of it. everything the
#command used to hold is still reachable here under its old name, for anything that reaches in for it.
import argparse
import json
import os
import sys

from comiclib.chapters.addresses import (agreement, chapter_word, chapters_from_list,  # noqa: F401
                                         chapters_from_urls, group_by_url, guess_by_url, numbers_in,
                                         read_in_order)
from comiclib.chapters.align import (align, anchor_kinds, by_written_order, describe, do_align,  # noqa: F401
                                     gap_notes, longest_run, place_recovered, recovered_files, save_gaps,
                                     unique_pairs, verify)
from comiclib.chapters.archive_page import (ArchiveReader, chapters_from_archive,  # noqa: F401
                                            chapters_from_events, drawn_heading, heading_says,
                                            pages_linked, read_archive)
from comiclib.chapters.chapterlist import (apply_fixes, chapter_record, chapters_every, compare_chapters,  # noqa: F401
                                           edit_fixes, list_fixes, plan, save_chapters, say_fixes,
                                           settle_chapters, show_chapters, try_archive)
from comiclib.chapters.index import (alignment_path, fill_sizes, head_size, index_path,  # noqa: F401
                                     joined_pages, one_page, read_index, remember_cache, save_alignment,
                                     walk)
from comiclib.chapters.links import (link_targets, looks_like_pages, page_at, page_shape,  # noqa: F401
                                     same_page, says_it_twice)
from comiclib.chapters.packing import (already_packed, chapter_contents, chapter_file,  # noqa: F401
                                       chapter_folder, comic_info, drop_single, pack, repack, tidy_name,
                                       verify_chapters)
from comiclib.chapters.pageops import insert_page, mark_recovered, refetch, renumber, shift_up  # noqa: F401
from comiclib.metadata import METADATA_FILE as metadata_file  # noqa: F401
from comiclib.pages import listing as folder_pages, page_key, page_number, plain_name  # noqa: F401
from comiclib.paths import config_folder  # noqa: F401
from comiclib.standin import (video_types, flash_types, link_types, a_web_address,  # noqa: F401
                              held_otherwise, address_in, archive_entry, stand_in, wrapped)


def setup():
    params = argparse.ArgumentParser(
        description="Line a comic's saved files up with the pages they came from.")
    params.add_argument("what", choices=["index", "align", "show", "chapters", "fix", "try", "pack",
                                         "refetch", "repack", "renumber", "recovered", "insert"],
                        help="index: walk the comic and line it up. align: line up a walk already done. "
                             "show: what the last alignment says. refetch: fetch again any page whose file "
                             "is not what the site serves. chapters: work out where the chapters start. "
                             "try: read an archive page and say what it would be read as, before walking "
                             "anything. "
                             "fix: put a chapter boundary right by hand. "
                             "renumber: rename the files so each carries its page number. "
                             "recovered: note a page the site has lost that you put back by hand. "
                             "insert: put in a page the comic's own links skip past. "
                             "pack: write one .cbz per chapter. "
                             "repack: write the .cbz afresh from the folder.")
    params.add_argument("folder", help="The comic's folder.")
    params.add_argument("--start", default=None, help="The comic's first page, when its metadata does not know.")
    params.add_argument("--restart", action='store_true', default=False,
                        help="With index, throw away what is already recorded and walk the comic from the "
                             "start. For a record that begins somewhere other than the first page, which "
                             "cannot be carried on from because its page numbers count from the wrong place.")
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
    params.add_argument("--every", type=int, default=None,
                        help="With chapters, cut the comic into parts of this many pages - 100 makes pages "
                             "1-100 one archive, 101-200 the next - for a comic with no chapters of its own "
                             "that has grown too big for a reader to open in one. Remembered, so later runs "
                             "keep cutting the pages it gains.")
    params.add_argument("--urls", action='store_true', default=False,
                        help="With chapters, work them out from the comic's own addresses, even when it "
                             "remembers an archive page.")
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
    params.add_argument("--url", default=None,
                        help="With insert, the address of the page to put in.")
    params.add_argument("--after", default=None,
                        help="With insert, the page it follows: its address or its number.")
    params.add_argument("--json", action='store_true', default=False,
                        help="With show, print every page as JSON, for a page picker to offer.")
    params.add_argument("--file", default=None,
                        help="With recovered, the filename of the page you put there by hand.")
    params.add_argument("--note", default=None,
                        help="With recovered, where it came from, kept with it in the metadata.")
    params.add_argument("--no-repack", action='store_true', default=False,
                        help="With fix, leave the chapter archives alone, even where the correction "
                             "changed what belongs in one.")
    params.add_argument("--page", default=None,
                        help="With refetch, only these pages, by number: --page 1 or --page 1,5,9.")
    params.add_argument("--as-named", action='store_true', default=False,
                        help="With refetch, save each page under the name the site's image has now and "
                             "remove the file that was there, for a page whose saved file is not its "
                             "image at all.")
    params.add_argument("--by-time", action='store_true', default=False,
                        help="With align, line the pages up by the order their files were written, for a "
                             "comic this scraper downloaded in one pass without numbering them.")
    params.add_argument("--at", default=None,
                        help="With fix, the page the correction is about: its address, or its page number.")
    params.add_argument("--label", default=None,
                        help="With fix, what the chapter starting at that page is called. Naming a chapter "
                             "that is already there moves it to this page rather than adding another.")
    params.add_argument("--drop", action='store_true', default=False,
                        help="With fix, no chapter starts at that page, whatever the archive or the "
                             "addresses say.")
    params.add_argument("--forget", action='store_true', default=False,
                        help="With fix, take back the correction made about that page.")
    params.add_argument("--clear", action='store_true', default=False,
                        help="With fix, take back every correction made about this comic.")
    params.add_argument("--script", default=None, help="Path to mirror_base.py.")
    params.add_argument("--like", default=None,
                        help="With try, one of the comic's page addresses, when its folder does not say.")
    params.add_argument("--cache", default=None,
                        help="The walk's cache file, when it is not the one in the config folder.")
    return params.parse_args()


def main():
    args = setup()
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder) and not (args.what == "try" and args.like):
        print("ERROR: {0} is not a folder.".format(folder))
        return 2
    if args.what == "show":
        path = alignment_path(index_path(folder, args.root, args))
        if not os.path.exists(path):
            print("ERROR: {0} has not been lined up yet.".format(folder))
            return 2
        saved = json.load(open(path, encoding='utf-8'))
        if args.json:
            #every page, for something that wants to offer them to choose from rather than read them
            json.dump({"comic": saved["comic"], "settled": saved.get("settled"),
                       "pages": [{"n": page["n"], "url": page["url"], "title": page.get("title"),
                                  "file": page.get("file")} for page in saved["pages"]]},
                      sys.stdout)
            return 0
        print("{0}: {1} pages, {2}".format(saved["comic"], len(saved["pages"]),
                                           "settled" if saved["settled"] else "NOT settled"))
        for page in saved["pages"][:5] + saved["pages"][-5:]:
            print("  {0:>5}  {1:<28} {2:<6} {3}".format(page["n"], str(page["file"])[:28], page["how"] or "-",
                                                        page["url"]))
        return 0
    if args.what == "try":
        if not args.archive:
            print("ERROR: say which page to read, with --archive.")
            return 2
        return try_archive(folder, args)
    if args.what == "pack":
        return pack(folder, args)
    if args.what == "chapters":
        return plan(folder, args)
    if args.what == "fix":
        return edit_fixes(folder, args)
    if args.what == "renumber":
        return renumber(folder, args)
    if args.what == "recovered":
        return mark_recovered(folder, args)
    if args.what == "insert":
        return insert_page(folder, args)
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
