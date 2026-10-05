#writes a mirror_metadata.json for a comic that already exists as a folder of pages or a .cbz, so
#update_comics.py can carry it on without re-downloading everything that is already there. #V 1.2
#
#this is the command; the work is in comiclib.adopt - scanning a library, the report, and adopting one
#comic. everything this held is still reachable here under its old name.
import argparse
import csv
import os
import sys

from comiclib.adopt.adopting import (adopt_one, build_archive, build_metadata, migrate_library,  # noqa: F401
                                     nearest_archive)
from comiclib.adopt.report import (editable_columns, read_report, report_columns, row_to_args,  # noqa: F401
                                   truthy, write_report)
from comiclib.adopt.unpacking import unpack_and_adopt
from comiclib.adopt.scan import (comic_folder, comic_names, every_archive, inside, inspect,  # noqa: F401
                                 is_page, list_pages, loose_pages, matching_archive, numbered,
                                 one_comic_split_up, page_types, pages_in_archives, prefixed,
                                 relative_output, survey)
from comiclib.metadata import METADATA_FILE, migrate as migrate_metadata  # noqa: F401

metadata_file = METADATA_FILE


def setup():
    params = argparse.ArgumentParser(
        description="Writes a mirror_metadata.json for a comic you already have, so update_comics.py can "
                    "resume it instead of scraping it again from the beginning.")
    params.add_argument("path", nargs='?',
                        help="The comic's folder, or its .cbz. Omit when using --scan.")
    params.add_argument("--root", default=".",
                        help="Library folder the comic sits inside. The saved --output is written relative to this, so it has to be the same folder update_comics.py is pointed at. Defaults to the working directory.")
    params.add_argument("--last-url", default=None, metavar="URL",
                        help="Address of the last page you already have. The next run re-saves that page and carries on from it.")
    params.add_argument("--next-url", default=None, metavar="URL",
                        help="Address of the first page you do NOT have. Use this instead of --last-url when re-saving the last page would produce a differently named duplicate.")
    params.add_argument("--ended", action='store_true', default=False,
                        help="The comic has finished. No address is needed and update_comics.py will skip it for good.")
    params.add_argument("--increment", type=int, default=None,
                        help="Page number of the last page you have, used with --prefix. Taken from the filenames, or the page count when they carry no number.")
    params.add_argument("--prefix", action=argparse.BooleanOptionalAction, default=None,
                        help="Number new pages with a filename prefix, which needs an --increment to count from. Off unless asked for, leaving pages named the way the site names them.")
    params.add_argument("--scan", action='store_true', default=False,
                        help="List everything under --root that holds pages but has no metadata yet, with what would be inferred for each.")
    params.add_argument("--all", action='store_true', default=False,
                        help="With --scan, also list comics that have already been adopted.")
    params.add_argument("--report", default=None, metavar="FILE",
                        help="Write the scan to a csv you can open in a spreadsheet. Fill in last_url, next_url, ended and cbz_path, then feed it back with --read-report. Re-running keeps anything already typed in.")
    params.add_argument("--read-report", default=None, metavar="FILE",
                        help="Adopt every comic in a filled-in report. Rows with no address and no ended mark are left alone.")
    params.add_argument("--cbz-path", default=None, metavar="PATH",
                        help="The .cbz this comic belongs to, when it is not beside the folder. Written relative to --root.")
    params.add_argument("--make-cbz", action=argparse.BooleanOptionalAction, default=True,
                        help="Build the archive when the cbz_path names one that is not there yet, rather than refusing. A name close to a real archive is still refused, since that is a typo. On by default.")
    params.add_argument("--unpack-to", default=None, metavar="FOLDER",
                        help="With a .cbz already in the library, unpack its pages into this folder (relative to --root, and empty or not there yet) and adopt the folder, keeping the .cbz as its archive. A comic kept only as an archive can be carried on, but not lined up against a walk or cut into chapters, which both work on loose pages.")
    params.add_argument("-n", "--dry-run", action='store_true', default=False,
                        help="Show the metadata that would be written without writing it.")
    params.add_argument("--migrate", action='store_true',
                        help="Rewrite every metadata file under --root in the current shape, pulling "
                             "the saved command apart into the settings block that replaced it. Safe "
                             "to run twice.")
    params.add_argument("--force", action='store_true', default=False,
                        help="Overwrite metadata that is already there.")
    return params.parse_args(), params


def main():
    args, params = setup()

    if args.migrate:
        if not os.path.isdir(args.root):
            print("ERROR: {0} is not a folder.".format(args.root))
            return 2
        print("Migrating metadata under {0}:".format(os.path.abspath(args.root)))
        return migrate_library(args.root, args.dry_run)

    if args.report or args.scan:
        rows = survey(args.root, args.all)
        if args.report:
            written = write_report(rows, args.report, args.root)
            print("Wrote {0} row(s) to {1}.".format(written, args.report))
            print("Fill in last_url (or next_url) and ended, check cbz_path, then run:")
            print("  python adopt_comic.py --read-report {0} --root {1}".format(args.report, args.root))
            return 0
        if not rows:
            print("Nothing under {0} needs adopting.".format(os.path.abspath(args.root)))
            return 0
        print("{0} candidate(s) under {1}:".format(len(rows), os.path.abspath(args.root)))
        for item, kind, details, nested in rows:
            rel = relative_output(item, args.root)
            if details is None:
                print("  {0:<46} {1}".format(rel[:46], kind))
                continue
            note = ""
            if nested and kind == "cbz x":
                note = "  ({0} archives)".format(nested)
            elif nested:
                note = "  (+{0} nested folder(s))".format(nested)
            print("  {0:<46} {1:<6} {2:>6} pages, {3:<11} last {4}{5}".format(
                rel[:46], kind, details["count"], details["style"], details["last_number"], note))
        return 0

    if args.read_report:
        if not os.path.exists(args.read_report):
            print("ERROR: {0} does not exist.".format(args.read_report))
            return 2
        try:
            rows = read_report(args.read_report)
        except (OSError, csv.Error) as error:
            print("ERROR: could not read {0}: {1}".format(args.read_report, error))
            return 2

        adopted, skipped, failed = 0, 0, []
        for row in rows:
            name = row.get("path", "").strip()
            if not name:
                continue
            row_args = row_to_args(row, args)
            #a row nobody filled in is not a failure, it just is not ready yet
            if not row_args.ended and not (row_args.last_url or row_args.next_url):
                skipped += 1
                continue
            ok, message = adopt_one(row_args, quiet=True)
            if ok:
                adopted += 1
                print("  adopted  {0:<42} {1}".format(name[:42], message))
            elif message.startswith("would adopt: "):
                adopted += 1
                print("  would    {0:<42} {1}".format(name[:42], message[13:]))
            else:
                failed.append((name, message))
                print("  PROBLEM  {0:<42} {1}".format(name[:42], message))
        print()
        print("{0} {1}, {2} left alone, {3} with problems.".format(
            adopted, "would be adopted" if args.dry_run else "adopted", skipped, len(failed)))
        return 1 if failed else 0

    if not args.path:
        params.error("a comic folder or .cbz is required unless --scan, --report, --read-report or --migrate is used")

    ok, message = unpack_and_adopt(args) if args.unpack_to else adopt_one(args)
    if ok:
        print("  wrote         : {0}".format(os.path.join(comic_folder(args.path), metadata_file)))
        return 0
    if message.startswith("would adopt: "):
        print("  (dry run, nothing written)")
        return 0
    print("ERROR: {0}".format(message))
    return 2


if __name__ == "__main__":
    sys.exit(main())
