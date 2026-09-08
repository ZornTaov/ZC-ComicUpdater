#writes a mirror_metadata.json for a comic that already exists as a folder of pages or a .cbz, so
#update_comics.py can carry it on without re-downloading everything that is already there. #V 1.1

import argparse
import csv
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone

metadata_file = "mirror_metadata.json"

#the report's columns. the first block is what the scan worked out and is there to read; the second is
#what you fill in. a row is adopted once it has an address or is marked ended, and ignored until then.
report_columns = [
    "path", "kind", "pages", "numbering", "last_number", "nested",
    "last_url", "next_url", "ended", "increment", "prefix", "cbz_path", "notes",
]
editable_columns = ["last_url", "next_url", "ended", "increment", "prefix", "cbz_path", "notes"]
page_types = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif', '.jxl')

#pages saved with --prefix start with the page number and an underscore; a folder that was renamed by hand
#is usually just the number. anything else carries no number at all.
prefixed = re.compile(r'^(\d+)_')
numbered = re.compile(r'^(\d+)\.')


def now_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def is_page(name):
    return name.lower().endswith(page_types)


def list_pages(path):
    #the pages in a folder or an archive, ignoring anything that is not an image. folders picked up over
    #the years hold stray files - a copy of the script, a Thumbs.db - that should not count as pages.
    if os.path.isfile(path) and path.lower().endswith('.cbz'):
        with zipfile.ZipFile(path) as zf:
            return sorted(os.path.basename(n) for n in zf.namelist() if is_page(n))
    pages = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        pages.extend(f for f in files if is_page(f))
    return sorted(pages)


def pages_in_archives(folder):
    #a comic kept only as .cbz volumes has no loose images. that is fine for one that has finished, and
    #the pages inside the archives are still the honest count.
    found = []
    if not os.path.isdir(folder):
        return found
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith('.cbz'):
            try:
                found.extend(list_pages(os.path.join(folder, name)))
            except (zipfile.BadZipFile, OSError):
                pass
    return found


def inspect(pages):
    #works out how the pages are numbered and what the last page number is
    highest, style = None, "unnumbered"
    for name in pages:
        match = prefixed.match(name)
        if match:
            style = "prefixed"
        else:
            match = numbered.match(name)
            if match and style != "prefixed":
                style = "numbered"
        if match:
            value = int(match.group(1))
            highest = value if highest is None else max(highest, value)
    return {"count": len(pages), "last_number": highest, "style": style}


def comic_folder(path):
    #a .cbz on its own still needs a folder to hold its metadata and receive new pages
    if os.path.isfile(path) and path.lower().endswith('.cbz'):
        return path[:-4]
    return path.rstrip('/\\')


def relative_output(folder, root):
    rel = os.path.relpath(os.path.abspath(folder), os.path.abspath(root))
    return rel.replace(os.sep, '/')


def build_metadata(args, folder, details, existing=None):
    output = relative_output(folder, args.root)
    increment = args.increment
    if increment is None:
        #filenames carrying no number leave the page count as the only guide to where the comic is up to.
        #starting from 1 instead would renumber a comic that already has thousands of pages.
        increment = details["last_number"]
        if increment is None:
            increment = details["count"]
        if args.next_url:
            increment += 1

    argv = ["--increment", str(increment), "--output", output]
    if args.prefix:
        argv.append("--prefix")
    #without this the scraper would build a second archive beside the pages and leave the real one alone
    archive = getattr(args, "cbz_path", None)
    if archive:
        argv.extend(["--cbz-path", archive])
    url = args.next_url or args.last_url
    if url:
        argv.append(url)

    kept = existing or {}
    created = kept.get("created", now_stamp())
    metadata = {
        "generator": "adopt_comic.py",
        "generator_version": "1.1",
        "created": created,
        "updated": now_stamp(),
        "adopted": True,
        #anything an earlier real scrape worked out is worth more than what can be guessed from filenames
        "image_xpath": kept.get("image_xpath"),
        "next_xpath": kept.get("next_xpath"),
        "runs": kept.get("runs", []),
        "first_page_url": kept.get("first_page_url"),
        "first_page_number": kept.get("first_page_number"),
        "source_url": url,
        "site": url.split('/')[2] if url and '//' in url else None,
        "output_folder": output,
        "archive_path": archive or None,
        "last_page_url": args.last_url,
        "last_page_number": details["last_number"],
        "resume_page_number": None if args.ended else increment,
        "last_image_url": None,
        "last_image_file": None,
        "page_count": details["count"],
        "completed": bool(args.ended),
        "command_line": kept.get("command_line"),
        "resume_command_line": None if args.ended else
            "python mirror_base.py {0}".format(" ".join(argv)),
        "resume_argv": None if args.ended else argv,
        #the numbering that was already in use, kept so it is obvious later why --prefix was or was not set
        "adopted_from": {
            "path": os.path.abspath(args.path),
            "pages_found": details["count"],
            "numbering": details["style"],
            "at": now_stamp(),
        },
    }
    if args.ended:
        #update_comics skips a comic marked this way, so a finished one is never checked again
        metadata["ended"] = True
    return metadata


def survey(root, show_all=False):
    #lists folders and archives that hold pages but have no metadata yet, so a migration can be worked
    #through without hunting for what is left
    folders, archives, adopted = [], [], []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        if metadata_file in files:
            dirs[:] = [] #a comic already; nothing below it is a separate one
            adopted.append(current)
            if show_all:
                folders.append([current, "adopted", None, 0])
            continue
        pages = [f for f in files if is_page(f)]
        if pages:
            folders.append([current, "folder", inspect(sorted(pages)), 0])
        for name in sorted(files):
            if not name.lower().endswith('.cbz') or os.path.isdir(os.path.join(current, name[:-4])):
                continue #a .cbz beside its own folder is the same comic, so only the folder is listed
            path = os.path.join(current, name)
            try:
                archives.append([path, "cbz", inspect(list_pages(path)), 0])
            except (zipfile.BadZipFile, OSError) as error:
                archives.append([path, "unreadable: {0}".format(error), None, 0])

    #a site mirror or a comic with chapter folders shows up as dozens of nested hits. only the outermost
    #is worth listing, with a note of how much sits beneath it, since that is the folder to adopt.
    tops = []
    for row in folders:
        parent = next((t for t in tops if row[0].startswith(t[0] + os.sep)), None)
        if parent is None:
            tops.append(row)
        else:
            parent[3] += 1

    #an archive whose pages sit in a folder elsewhere in the library is that same comic, not another one.
    #it is dropped here and named in the folder's cbz_path instead, so each comic is one row.
    #comics that are already adopted still own their archive, so it must not come back as a candidate
    folder_paths = [row[0] for row in tops] + adopted
    folder_names = set()
    for folder in folder_paths:
        folder_names.update(comic_names(folder, root, folder_paths))
    archives = [a for a in archives if os.path.basename(a[0])[:-4].lower() not in folder_names]

    #archives sitting together in a sub folder are ambiguous: volumes of one comic, chapters, or a set of
    #separate comics filed under an author. that is one decision to look at rather than one row per file.
    #archives at the top of the library are listed individually, since there each one is its own comic.
    if not show_all:
        root_dir = os.path.abspath(root)
        grouped, singles = {}, []
        for row in archives:
            parent = os.path.dirname(row[0])
            siblings = [a[0] for a in archives if os.path.dirname(a[0]) == parent]
            if len(siblings) < 2 or os.path.abspath(parent) == root_dir or not one_comic_split_up(siblings):
                singles.append(row)
                continue
            if parent not in grouped:
                grouped[parent] = [parent, "cbz x", {"count": 0, "last_number": None,
                                                     "style": "look inside"}, 0]
            grouped[parent][2]["count"] += (row[2] or {}).get("count", 0)
            grouped[parent][3] += 1
        archives = sorted(singles) + [grouped[k] for k in sorted(grouped)]

    return (folders if show_all else tops) + archives


def truthy(text):
    return str(text or "").strip().lower() in ("y", "yes", "true", "1", "x", "t")


def every_archive(root):
    #every .cbz in the library, so a folder can be matched to the archive it belongs to even when the two
    #live in different trees
    found = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in files:
            if name.lower().endswith('.cbz'):
                found.setdefault(name[:-4].lower(), []).append(os.path.join(current, name))
    return found


def one_comic_split_up(paths):
    #volumes or chapters of a single comic share their name - "Dr McNinja 04", "Ch.12", "001". a folder of
    #separate comics filed under an author or a site does not. leading numbering is stripped first, so
    #"[3] NPC - ..." still lines up with "[11] NPC - ...".
    stems = [re.sub(r'^[\[\(]?\d+[\]\)]?[\s._-]*', '', os.path.basename(p)[:-4]).lower() for p in paths]
    if all(not stem for stem in stems):
        return True #nothing but numbers for names, so they are volumes
    return len(os.path.commonprefix(stems).strip()) >= 3


def comic_names(folder, root, folder_paths):
    #the names an archive for this comic might carry. usually just the folder's own name, but a site mirror
    #keeps its pages somewhere like TSAT/www.example.com, and the archive is named for the folder above.
    #an ancestor holding more than one comic is a grouping folder, not this comic, so the walk stops there.
    names = [os.path.basename(folder).lower()]
    root_abs = os.path.abspath(root)
    current = os.path.dirname(os.path.abspath(folder))
    while current != root_abs and current.startswith(root_abs) and os.path.dirname(current) != current:
        below = sum(1 for p in folder_paths if os.path.abspath(p).startswith(current + os.sep))
        if below > 1:
            break
        names.append(os.path.basename(current).lower())
        current = os.path.dirname(current)
    return names


def nearest_archive(missing):
    #a cbz_path is nearly always a name typed slightly differently, so say what was probably meant
    folder = os.path.dirname(missing)
    stem = os.path.basename(missing)[:-4].lower().replace(' ', '').replace('_', '')
    if not os.path.isdir(folder):
        return ""
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith('.cbz') and name[:-4].lower().replace(' ', '').replace('_', '') == stem:
            return ", did you mean {0}".format(name)
    return ""


def matching_archive(folder, root, archives, folder_paths):
    #a library that keeps pages under Uncompressed/ and archives at the top has to be told which is which.
    #the names almost always agree, so that is guessed here and left in the report to be corrected.
    beside = os.path.abspath(folder) + '.cbz'
    for name in comic_names(folder, root, folder_paths):
        for candidate in archives.get(name, []):
            if os.path.abspath(candidate) != beside:
                return relative_output(candidate, root)
    return ""


def write_report(rows, path, root, keep_edits=True):
    #re-running the report keeps whatever was already typed in, so a migration can be picked up later
    previous, by_name = {}, {}
    if keep_edits and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for old in csv.DictReader(f):
                    was_at = old.get("path", "")
                    previous[was_at] = old
                    by_name.setdefault(os.path.basename(was_at).lower(), []).append(old)
        except (OSError, csv.Error):
            pass

    archives = every_archive(root)
    folder_paths = [item for item, kind, _, _ in rows if kind == "folder"]
    #two archives sharing a name are usually one file kept in two places; worth pointing out rather than
    #silently picking one
    twice = {name for name, found in archives.items() if len(found) > 1}
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=report_columns)
        writer.writeheader()
        for item, kind, details, nested in rows:
            rel = relative_output(item, root)
            was = previous.get(rel)
            if was is None:
                #a library gets reorganised; falling back to the comic's own name keeps the answers that
                #were typed in against its old location, as long as the name still picks out one comic
                same = by_name.get(os.path.basename(rel).lower(), [])
                was = same[0] if len(same) == 1 else None
            if was is None:
                #a folder that used to be listed as one row may now be listed as its separate files, so
                #what was answered for the folder still applies to everything that was inside it
                parent = by_name.get(os.path.basename(os.path.dirname(rel)).lower(), [])
                was = dict(parent[0], cbz_path="") if len(parent) == 1 else {}
            row = {
                "path": rel,
                "kind": kind,
                "pages": (details or {}).get("count", ""),
                "numbering": (details or {}).get("style", ""),
                "last_number": (details or {}).get("last_number", ""),
                "nested": nested or "",
            }
            for column in editable_columns:
                row[column] = was.get(column, "")
            #a kept archive path that no longer points anywhere is left over from how the library used to
            #be arranged, so it is paired again. one that matches nothing is kept as typed, to be seen and
            #corrected rather than quietly dropped.
            stale = row["cbz_path"] and not os.path.isfile(
                os.path.join(root, row["cbz_path"].replace('/', os.sep)))
            if kind == "folder" and (not row["cbz_path"] or stale):
                row["cbz_path"] = matching_archive(item, root, archives, folder_paths) or row["cbz_path"]
            if not row["notes"] and kind == "cbz x":
                row["notes"] = "several archives here; point a row at one file to adopt it"
            if not row["notes"] and kind == "cbz" and os.path.basename(item)[:-4].lower() in twice:
                row["notes"] = "another archive in the library has this same name"
            writer.writerow(row)
    return len(rows)


def read_report(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return [row for row in csv.DictReader(f)]


def row_to_args(row, base):
    #turns one filled-in report line into the same arguments a single adopt call would take
    args = argparse.Namespace(**vars(base))
    args.path = os.path.join(base.root, row.get("path", "").replace('/', os.sep))
    args.last_url = (row.get("last_url") or "").strip() or None
    args.next_url = (row.get("next_url") or "").strip() or None
    args.ended = truthy(row.get("ended"))
    args.cbz_path = (row.get("cbz_path") or "").strip() or None
    increment = (row.get("increment") or "").strip()
    args.increment = int(increment) if increment.isdigit() else None
    prefix = (row.get("prefix") or "").strip()
    args.prefix = None if not prefix else truthy(prefix)
    return args


def adopt_one(args, quiet=False):
    #returns (written, message); shared by the single adopt and by reading a report
    if not os.path.exists(args.path):
        return False, "does not exist"
    if args.last_url and args.next_url:
        return False, "give either last_url or next_url, not both"
    if not args.ended and not (args.last_url or args.next_url):
        return False, "needs an address, or ended"

    #a cbz_path that points nowhere would quietly build a second archive and leave the real one behind,
    #which nothing would notice until pages stopped appearing in the reader
    archive = getattr(args, "cbz_path", None)
    archive_full = None
    if archive:
        archive_full = os.path.join(args.root, archive.replace('/', os.sep))
        if not os.path.isfile(archive_full):
            return False, "cbz_path {0} does not exist{1}".format(archive, nearest_archive(archive_full))

    try:
        pages = list_pages(args.path)
    except (zipfile.BadZipFile, OSError) as error:
        return False, "could not read: {0}".format(error)
    if not pages:
        #a comic that arrived as a finished .cbz has no loose pages to look at, but the ones inside the
        #archive are numbered the same way and answer the same questions. the folder only has to hold
        #what a later run adds to it, so an empty one beside a real archive is a comic, not a mistake.
        if archive_full:
            try:
                pages = list_pages(archive_full)
            except (zipfile.BadZipFile, OSError) as error:
                return False, "could not read {0}: {1}".format(archive, error)
        if not pages:
            pages = pages_in_archives(args.path)
    if not pages:
        return False, "no images found"

    details = inspect(pages)
    if args.prefix is None:
        #left blank, a comic keeps whatever filename the site gives its pages. prefix and increment go
        #together: numbering is asked for explicitly, the same way mirror_base leaves -p off by default.
        args.prefix = False

    folder = comic_folder(args.path)
    target = os.path.join(folder, metadata_file)
    existing = None
    if os.path.exists(target):
        if not args.force:
            return False, "already has metadata (use --force)"
        try:
            with open(target, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (ValueError, OSError):
            pass

    metadata = build_metadata(args, folder, details, existing)

    if not quiet:
        print("{0}".format(os.path.abspath(args.path)))
        print("  pages found   : {0} ({1}, last number {2})".format(
            details["count"], details["style"], details["last_number"]))
        print("  output folder : {0}".format(metadata["output_folder"]))
        print("  prefix        : {0}".format("yes" if args.prefix else "no"))
        if metadata.get("archive_path"):
            print("  archive       : {0}".format(metadata["archive_path"]))
        if args.ended:
            print("  ended         : yes, update_comics.py will skip it")
        else:
            print("  resumes with  : {0}".format(metadata["resume_command_line"]))

    #worked out before the dry run returns, so a dry run can say what it would have done
    summary = "ended" if args.ended else "resumes at page {0}".format(metadata["resume_page_number"])
    if metadata.get("archive_path"):
        summary += ", packs into {0}".format(metadata["archive_path"])
    if args.dry_run:
        return False, "would adopt: " + summary

    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
        f.write('\n')
    return True, summary


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
    params.add_argument("-n", "--dry-run", action='store_true', default=False,
                        help="Show the metadata that would be written without writing it.")
    params.add_argument("--force", action='store_true', default=False,
                        help="Overwrite metadata that is already there.")
    return params.parse_args(), params


def main():
    args, params = setup()

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
        params.error("a comic folder or .cbz is required unless --scan, --report or --read-report is used")

    ok, message = adopt_one(args)
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
