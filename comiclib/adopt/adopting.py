#writing the metadata that makes a folder of pages a comic update_comics can carry on, building its archive
#where one is named and missing, and bringing old metadata up to the current shape.
import json
import os
import zipfile

from comiclib import cbz
from comiclib.adopt.scan import comic_folder, inside, inspect, list_pages, loose_pages, pages_in_archives
from comiclib.adopt.scan import relative_output
from comiclib.metadata import METADATA_FILE as metadata_file, migrate as migrate_metadata, now_stamp
from comiclib.metadata import settings_to_argv


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

    #without this the scraper would build a second archive beside the pages and leave the real one alone
    archive = getattr(args, "cbz_path", None) or None
    url = args.next_url or args.last_url

    kept = existing or {}
    old_state = kept.get("state") or {}
    old_history = kept.get("history") or {}
    created = kept.get("created", now_stamp())
    metadata = {
        "schema": 2,
        "generator": "adopt_comic.py",
        "generator_version": "1.2",
        "created": created,
        "updated": now_stamp(),
        #the one place to edit. update_comics.py builds the scrape command from this and nowhere else,
        #so a value corrected here is corrected everywhere, with no second copy to fall out of step
        "settings": {
            "url": url,
            "output": output,
            "cbz_path": archive,
            "increment": increment,
            "prefix": bool(args.prefix),
            "javascript": False,
            "firefox": False,
            "waittime": 0,
            "cbz": True,
            #update_comics.py leaves a comic marked this way alone from then on
            "ended": bool(args.ended),
        },
        "state": {
            "site": url.split('/')[2] if url and '//' in url else None,
            "page_count": details["count"],
            "completed": bool(args.ended),
            #anything an earlier real scrape worked out is worth more than what can be guessed from
            #filenames, so a re-adopt keeps it
            "image_xpath": old_state.get("image_xpath", kept.get("image_xpath")),
            "next_xpath": old_state.get("next_xpath", kept.get("next_xpath")),
            "last_image_url": None,
            "last_image_file": None,
        },
        "history": {
            "first_page_url": old_history.get("first_page_url", kept.get("first_page_url")),
            "first_page_number": old_history.get("first_page_number", kept.get("first_page_number")),
            "adopted": True,
            #the numbering already in use, kept so it is obvious later why prefix was or was not set
            "adopted_from": {
                "path": os.path.abspath(args.path),
                "pages_found": details["count"],
                "numbering": details["style"],
                "at": now_stamp(),
            },
            "runs": old_history.get("runs", kept.get("runs", [])),
        },
    }
    return metadata


def nearest_archive(missing):
    #a cbz_path is nearly always a name typed slightly differently, so say what was probably meant
    folder = os.path.dirname(missing)
    stem = os.path.basename(missing)[:-4].lower().replace(' ', '').replace('_', '')
    #a path naming a shelf that is not there yet is checked one level up as well, so the same comic
    #already sitting loose on the shelf is spotted before a folder is made for a second copy of it
    for at in (folder, os.path.dirname(folder)):
        if not at or not os.path.isdir(at):
            continue
        for name in sorted(os.listdir(at)):
            if name.lower().endswith('.cbz') and name[:-4].lower().replace(' ', '').replace('_', '') == stem:
                return ", did you mean {0}".format(os.path.join(os.path.basename(at), name))
        if at == folder:
            #the folder exists and holds nothing by that name, so there is nothing more to guess at
            break
    return ""


def build_archive(folder, archive):
    #packs the comic into an archive that is not there yet. a cbz_path naming a file that does not
    #exist is nearly always a library being filled in rather than a mistake, so it is built instead of
    #refused; a name that is only slightly different from a real one is caught before we ever get here.
    pages = loose_pages(folder)
    if not pages:
        return 0
    #packed the way a scrape packs one, metadata last, so a later scrape adds to it rather than starting over
    held = [metadata_file] if os.path.isfile(os.path.join(folder, metadata_file)) else []
    cbz.write(archive, folder, pages + held)
    return len(pages)


def adopt_one(args, quiet=False):
    #returns (written, message); shared by the single adopt and by reading a report
    if not os.path.exists(args.path):
        return False, "does not exist"
    if args.last_url and args.next_url:
        return False, "give either last_url or next_url, not both"
    if not args.ended and not (args.last_url or args.next_url):
        return False, "needs an address, or ended"

    #a cbz_path one letter away from a real archive would quietly build a second one and leave the real
    #one behind, which nothing would notice until pages stopped appearing in the reader. a name nothing
    #resembles is a shelf being filled in, so the archive is built rather than refused.
    archive = getattr(args, "cbz_path", None)
    archive_full = None
    to_build = None
    if archive:
        archive_full = os.path.join(args.root, archive.replace('/', os.sep))
        if not os.path.isfile(archive_full):
            near = nearest_archive(archive_full)
            if near:
                return False, "cbz_path {0} does not exist{1}".format(archive, near)
            if not getattr(args, "make_cbz", True):
                return False, "cbz_path {0} does not exist".format(archive)
            to_build = archive_full

    try:
        pages = list_pages(args.path)
    except (zipfile.BadZipFile, OSError) as error:
        return False, "could not read: {0}".format(error)
    if not pages:
        #a comic that arrived as a finished .cbz has no loose pages to look at, but the ones inside the
        #archive are numbered the same way and answer the same questions. the folder only has to hold
        #what a later run adds to it, so an empty one beside a real archive is a comic, not a mistake.
        if archive_full and not to_build:
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
    if to_build:
        #an archive built among the pages instead of on the shelf beside them is what a --root pointed
        #one level too deep produces, and it takes the saved output path down with it, so it is refused
        tree, shelf = cbz.shelf(folder)
        if shelf and inside(to_build, tree):
            return False, ("cbz_path {0} would be built at {1}, in among the pages rather than on "
                           "this library's shelf {2} - is --root one folder too deep?".format(
                               archive, os.path.abspath(to_build), shelf))
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
        print("  output folder : {0}".format(metadata["settings"]["output"]))
        print("  prefix        : {0}".format("yes" if args.prefix else "no"))
        if metadata["settings"]["cbz_path"]:
            print("  archive       : {0}".format(metadata["settings"]["cbz_path"]))
        if args.ended:
            print("  ended         : yes, update_comics.py will skip it")
        else:
            print("  resumes with  : python mirror_base.py {0}".format(
                " ".join(settings_to_argv(metadata["settings"]))))

    #worked out before the dry run returns, so a dry run can say what it would have done
    summary = "ended" if args.ended else "resumes at page {0}".format(metadata["settings"]["increment"])
    if metadata["settings"]["cbz_path"]:
        summary += ", packs into {0}".format(metadata["settings"]["cbz_path"])
    waiting = len(loose_pages(folder)) if to_build else 0
    if to_build and not waiting:
        summary += " (nothing loose to build it from yet)"
        if not quiet:
            print("  archive       : {0}, nothing loose to build it from yet".format(archive))
    if args.dry_run:
        if waiting:
            summary += " (would build it from {0} page(s))".format(waiting)
            if not quiet:
                print("  would build   : {0} from {1} page(s)".format(archive, waiting))
        return False, "would adopt: " + summary

    os.makedirs(folder, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
        f.write('\n')

    #built after the metadata is written, so the archive carries the same mirror_metadata.json a
    #scrape-made one would and a comic is never left adopted-but-unpacked if the pack fails
    if to_build and waiting:
        try:
            made = build_archive(folder, to_build)
        except (OSError, zipfile.BadZipFile) as error:
            if not quiet:
                print("  archive       : {0} could not be built: {1}".format(archive, error))
            return True, summary + ", but building it failed: {0}".format(error)
        summary += " (built it from {0} page(s))".format(made)
        if not quiet:
            print("  archive built : {0} from {1} page(s)".format(archive, made))
    return True, summary


def migrate_library(root, dry_run=False):
    #rewrites every sidecar under root in the current shape. safe to run twice: a file already in the
    #new shape is left exactly as it is rather than being rewritten with a new timestamp.
    done, already, failed = 0, 0, []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        if metadata_file not in files:
            continue
        dirs[:] = []
        path = os.path.join(current, metadata_file)
        name = os.path.relpath(current, root).replace(os.sep, '/')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                old = json.load(f)
            fresh = migrate_metadata(old)
        except (ValueError, OSError, AttributeError) as error:
            failed.append((name, str(error)))
            print("  PROBLEM  {0:<42} {1}".format(name[:42], error))
            continue
        if fresh is None:
            already += 1
            continue
        settings = fresh["settings"]
        note = "page {0}{1}{2}".format(settings["increment"],
                                       ", prefix" if settings["prefix"] else "",
                                       ", ended" if settings["ended"] else "")
        if dry_run:
            print("  would    {0:<42} {1}".format(name[:42], note))
        else:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(fresh, f, indent=2)
                    f.write('\n')
            except OSError as error:
                failed.append((name, str(error)))
                print("  PROBLEM  {0:<42} {1}".format(name[:42], error))
                continue
            print("  migrated {0:<42} {1}".format(name[:42], note))
        done += 1
    print()
    print("{0} {1}, {2} already current, {3} with problems.".format(
        done, "would be migrated" if dry_run else "migrated", already, len(failed)))
    return 2 if failed else 0
