#the chapter list a comic keeps in its metadata: worked out from whichever source there is, corrected by
#hand, and saved. a chapter runs until the next one starts, so filler and guest pages stay where they were
#published.
import os
import re

import requests

from comiclib.chapters.addresses import chapters_from_list, chapters_from_urls, guess_by_url
from comiclib.chapters.archive_page import (ArchiveReader, chapters_from_archive, chapters_from_events,
                                            pages_linked, read_archive)
from comiclib.chapters.index import joined_pages
from comiclib.chapters.links import page_at, same_page
from comiclib.chapters.packing import pack
from comiclib.metadata import METADATA_FILE as metadata_file, now_stamp as time_stamp, read as read_metadata
from comiclib.metadata import write as write_metadata


def settle_chapters(found, pages, shift=0):
    #chapters are read in the order the comic is read, and each one runs until the next one starts, so
    #anything between them - filler, guest art, a flash page with no file - stays where it was published
    for chapter in found:
        chapter["start_page"] = max(1, min(len(pages), chapter["start_page"] + shift))
    found = sorted(found, key=lambda chapter: chapter["start_page"])
    settled, seen = [], set()
    for chapter in found:
        if chapter["start_page"] in seen:
            continue #two headings pointing at one page is one chapter
        seen.add(chapter["start_page"])
        settled.append(chapter)
    by_page = {page["n"]: page for page in pages}
    for at, chapter in enumerate(settled):
        ends = settled[at + 1]["start_page"] - 1 if at + 1 < len(settled) else pages[-1]["n"]
        chapter["number"] = at + 1
        chapter["end_page"] = ends
        chapter["pages"] = ends - chapter["start_page"] + 1
        start = by_page.get(chapter["start_page"], {})
        chapter["start_url"] = start.get("url")
        chapter["start_file"] = start.get("file")
        chapter.pop("pages_listed", None)
    return settled


def apply_fixes(found, pages, fixes):
    #corrections made by hand, kept apart from whatever rule worked the chapters out so that reading the
    #archive again, or the addresses again, never throws them away. each one says either that a chapter
    #starts at a page, or that one does not - which covers a boundary in the wrong place, a chapter the
    #site named oddly, and a heading that was never a chapter at all.
    took, missed = [], []
    for fix in fixes or []:
        at = page_at(pages, fix.get("url")) if fix.get("url") else fix.get("page")
        if not at or at > len(pages):
            missed.append(fix.get("url") or fix.get("page"))
            continue
        found = [chapter for chapter in found if chapter["start_page"] != at]
        if not fix.get("drop"):
            label = fix.get("label") or "Chapter"
            #naming a chapter that is already there moves it here rather than making a second one of the
            #same name: a cover the artist named oddly is the same chapter, starting a page earlier. that
            #holds for one this rule found and for one an earlier correction put somewhere else.
            found = [chapter for chapter in found if (chapter.get("label") or "") != label]
            found.append({"label": label, "start_page": at, "by_hand": True})
        took.append((at, None if fix.get("drop") else fix.get("label")))
    return found, took, missed


def say_fixes(took, missed):
    for at, label in took:
        print("  by hand: {0}".format("no chapter starts at page {0}".format(at) if label is None
                                      else "page {0} starts {1}".format(at, label)))
    for where in missed:
        print("  by hand: {0} is not a page of this comic, so that correction did nothing".format(where))


def show_chapters(folder, chapters, pages, listed=None):
    print("{0}: {1} chapter(s) over {2} page(s)".format(folder, len(chapters), len(pages)))
    if listed is not None:
        print("  the archive listed {0} of this comic's {1} pages".format(listed, len(pages)))
    before = chapters[0]["start_page"] - 1 if chapters else 0
    if before:
        print("  {0} page(s) come before the first chapter starts".format(before))
    print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}".format("no", "label", "from", "to", "pages", "starts at"))
    for chapter in chapters:
        print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}{6}".format(
            chapter["number"], (chapter["label"] or "")[:44], chapter["start_page"], chapter["end_page"],
            chapter["pages"], (chapter["start_file"] or "?"),
            "  <- by hand" if chapter.get("by_hand") else ""))
    odd = [c for c in chapters if c["pages"] <= 1]
    if odd:
        print("  {0} chapter(s) hold one page or none, which usually means a heading was read wrongly: "
              "{1}".format(len(odd), [c["number"] for c in odd[:8]]))


def chapter_record(chapter):
    kept = {"number": chapter["number"], "label": chapter["label"], "start_page": chapter["start_page"],
            "end_page": chapter["end_page"], "pages": chapter["pages"], "start_url": chapter["start_url"],
            "start_file": chapter["start_file"]}
    if chapter.get("by_hand"):
        kept["by_hand"] = True
    return kept


def save_chapters(folder, chapters, source, source_url=None):
    metadata = read_metadata(folder)
    if not metadata:
        print("  no metadata here, so the chapters were not saved")
        return 1
    was = metadata.get("chapters") or {}
    metadata["chapters"] = {
        "source": source,
        "source_url": source_url,
        "checked": time_stamp(),
        "list": [chapter_record(c) for c in chapters],
    }
    #a correction is about this comic, not about one run of one rule, and where the archives are and when
    #they were written describes what is on disk, not this reading. neither is the reading's to throw away
    for kept in ("fixes", "packed", "folder"):
        if was.get(kept):
            metadata["chapters"][kept] = was[kept]
    write_metadata(folder, metadata)
    print("  saved {0} chapter(s) into {1}".format(len(chapters), os.path.join(folder, metadata_file)))
    return 0


def compare_chapters(was, now):
    #what changed, in the terms that matter: a chapter added at the end is safe to take, while one that
    #moved or vanished means pages would leave archives that already hold them
    was = was or []
    older = [(c["start_page"], c.get("label")) for c in was]
    newer = [(c["start_page"], c.get("label")) for c in now]
    if older == newer[:len(older)]:
        return "same" if len(newer) == len(older) else "longer", newer[len(older):]
    moved = [old for old, fresh in zip(older, newer) if old != fresh]
    return "changed", moved


def try_archive(folder, args):
    #a look at an archive page on its own: what it would be read as, before a comic is walked for the
    #addresses that would let every heading be turned into a page number
    metadata = read_metadata(folder) if folder and os.path.isdir(folder) else {}
    known = ((metadata.get("settings") or {}).get("url")
             or (metadata.get("history") or {}).get("first_page_url") or args.like)
    if not known:
        print("Nothing says what this comic's page addresses look like. Pass --like with one of its pages.")
        return 2
    reader = ArchiveReader()
    try:
        reader.feed(read_archive(args.archive, args.browser, args.script))
    except (requests.RequestException, OSError) as error:
        print("Could not read {0}: {1}".format(args.archive, error))
        return 1

    #the archive's own order stands in for the comic's, so the very code a real run uses can read it:
    #a preview that worked things out its own way would not be a preview of anything
    archive_links, order = pages_linked(reader.events, args.archive, known)
    pretend = [{"n": at, "url": where} for at, where in enumerate(archive_links, 1)]
    found, pages = chapters_from_events(reader.events, order, args.archive)
    found = settle_chapters(found, pretend) if found and pretend else []

    print("{0}".format(args.archive))
    print("  pages of this comic linked: {0}, looking like {1}".format(len(archive_links), known))
    print("  chapters it would read: {0}".format(len(found)))
    for chapter in found[:40]:
        print("  {0:<4} {1:<46} {2:>4} page(s) listed, starts at {3}".format(
            chapter["number"], (chapter["label"] or "")[:46], chapter["pages"],
            (chapter["start_url"] or "")[-52:]))
    if len(found) > 40:
        print("  ... and {0} more".format(len(found) - 40))
    said = [chapter["pages_said"] for chapter in found if chapter.get("pages_said")]
    if said:
        print("  {0} of these say how long they are, adding up to {1} page(s), against {2} page(s) "
              "linked here".format(len(said), sum(said), len(archive_links)))
        if sum(said) > len(archive_links) * 1.5:
            print("      so this page lists where chapters start, not every page: the comic has to be "
                  "walked for the pages in between.")
        quiet = [chapter for chapter in found if not chapter.get("pages_said")]
        if quiet and len(quiet) <= max(3, len(found) // 10):
            #on a page where almost every heading states a length, one that does not is usually not a
            #chapter at all but some other section that happens to link into the comic
            print("      {0} of them say nothing about their length, unlike the rest, so look at "
                  "whether they are chapters at all:".format(len(quiet)))
            for chapter in quiet[:5]:
                print("        {0:<40} starts at {1}".format(
                    (chapter["label"] or "")[:40], (chapter["start_url"] or "")[-46:]))
    if not found:
        print("  Nothing was read as a chapter. Either no link on that page is a page of this comic - check "
              "what --like says they look like - or the page needs --browser to build itself first.")
        return 1
    #an archive with no chapter headings reads as one heading over everything, which says nothing about
    #the comic. the addresses it links to might still say where the chapters are, so they are tried here.
    biggest = max((chapter["pages"] for chapter in found), default=0)
    if len(found) < 3 or biggest > len(archive_links) * 0.8:
        by_url, distinct = guess_by_url(archive_links)
        print()
        if by_url:
            print("  The headings say little, but the addresses do: {0} chapter(s) across {1} distinct "
                  "page(s).".format(len(by_url), distinct))
            for at, (label, held) in enumerate(by_url[:8], 1):
                print("  {0:<4} {1:<40} {2:>4} page(s)".format(at, label[:40], held))
            if len(by_url) > 8:
                print("  ... and {0} more".format(len(by_url) - 8))
            print("  Run chapters.py chapters <folder> with no --archive to use those; the comic's own "
                  "order decides where each one starts.")
        else:
            print("  Neither the headings nor the addresses say where chapters start here. A list of "
                  "chapter starts (--list) is the way in.")
    print("  Nothing was saved. This only says how the page reads; page numbers need the comic walked "
          "once (chapters.py index).")
    return 0


def plan(folder, args):
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    metadata = read_metadata(folder)
    known = metadata.get("chapters") or {}
    if (not args.archive and not args.list and not args.urls
            and known.get("source") == "archive" and known.get("source_url")):
        #the comic remembers where its chapters are listed, so keeping them current needs no arguments
        args.archive = known["source_url"]
        print("Reading the archive this comic remembers: {0}".format(args.archive))
    listed = None
    if args.archive and not args.urls:
        found, listed = chapters_from_archive(args.archive, pages, args.browser, args.script)
        source, source_url = "archive", args.archive
    elif args.list:
        found, source, source_url = chapters_from_list(args.list, pages), "list", None
    elif known.get("source") == "hand" and known.get("fixes"):
        #this comic's chapters were set by hand, so there is nothing to re-read: the corrections are the
        #source, and working the addresses out afresh would throw them away
        print("This comic's chapters were set by hand; keeping them.")
        found, source, source_url = [], "hand", None
    else:
        found, source, source_url = chapters_from_urls(pages), "urls", None
        if not found:
            print("Nothing in this comic's addresses says where a chapter starts. Give --archive with its "
                  "archive page, --list with a file of chapter start addresses, or set the boundaries by "
                  "hand with chapters.py fix.")
            return 1
    if not found and source != "hand":
        print("No chapters found.")
        return 1
    found, took, missed = apply_fixes(found, pages, known.get("fixes"))
    say_fixes(took, missed)
    chapters = settle_chapters(found, pages, args.shift)
    show_chapters(folder, chapters, pages, listed)
    how, what = compare_chapters(known.get("list"), chapters)
    if known.get("list"):
        if how == "same":
            print("  the same chapters as before.")
        elif how == "longer":
            print("  {0} chapter(s) more than before: {1}".format(
                len(what), ", ".join("{0} at page {1}".format(label, at) for at, label in what[:4])))
        else:
            print("  WARNING: this moves chapters that already have archives written for them: {0}{1}".format(
                ["page {0}".format(at) for at, label in what[:4]], "..." if len(what) > 4 else ""))
    if len(chapters) < 2 and not args.force:
        #a comic in one chapter is a comic that is not chaptered. saving this replaces the single archive
        #with a single archive under another name, which is the sort of thing that looks like it worked.
        print("  this reads as one chapter over the whole comic, which is what a page with no chapter "
              "headings looks like - not a comic in one chapter. Nothing saved. Use --archive with a "
              "page that does list chapters, --urls if the addresses number them, or --list.")
        return 1
    if not args.save:
        print("  nothing saved. Run it again with --save once this looks right.")
        return 0
    if how == "changed" and not args.force:
        print("  nothing saved, because pages would move between archives that already exist. Look at it, "
              "then run it again with --force if that is what you want.")
        return 1
    code = save_chapters(folder, chapters, source, source_url)
    if not code and how != "same" and known.get("packed"):
        #nothing repacks itself: an archive holding the old boundary keeps holding it until pack is run
        print("  the chapter archives still hold the old boundaries. Run: chapters.py pack {0}".format(folder))
    return code


def list_fixes(fixes, pages):
    if not fixes:
        print("  nothing has been corrected by hand.")
        return
    for fix in fixes:
        at = page_at(pages, fix.get("url")) if fix.get("url") else fix.get("page")
        print("  page {0:<5} {1:<44} {2}".format(
            at if at else "?", "(no chapter starts here)" if fix.get("drop") else (fix.get("label") or ""),
            fix.get("url") or ""))


def edit_fixes(folder, args):
    #a boundary put right by hand. the correction is written down as a correction rather than edited into
    #the list, so working the chapters out again - from a fresh archive reading, or fresh addresses - keeps
    #it. it is anchored to the page's own address, so it still means the same page after the comic grows.
    metadata = read_metadata(folder)
    if not metadata:
        print("ERROR: no metadata in {0}.".format(folder))
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    block = metadata.setdefault("chapters", {})
    fixes = list(block.get("fixes") or [])
    if not args.at and not args.clear:
        print("{0}: {1} correction(s) by hand".format(folder, len(fixes)))
        list_fixes(fixes, pages)
        return 0
    if args.clear:
        print("forgotten: all {0} correction(s)".format(len(fixes)))
        fixes = []
    if args.at:
        where, at = str(args.at).strip(), None
        if re.match(r'^\d+$', where):
            at = int(where)
            page = next((p for p in pages if p["n"] == at), None)
            if page is None:
                print("ERROR: this comic has no page {0}; it has {1}.".format(at, len(pages)))
                return 2
            where = page["url"]
        else:
            at = page_at(pages, where)
            if at is None:
                print("ERROR: {0} is not a page of this comic. Give one of its page addresses, or a page "
                      "number.".format(where))
                return 2
        if not args.drop and not args.forget and not args.label:
            print("ERROR: say what the chapter starting there is called, with --label, or say --drop for "
                  "no chapter there, or --forget to take back an earlier correction.")
            return 2
        fixes = [fix for fix in fixes if same_page(str(fix.get("url") or "")) != same_page(where)]
        if args.label:
            #a chapter is corrected to one place, not to every place it has been moved to in turn
            fixes = [fix for fix in fixes if (fix.get("label") or "") != args.label]
        if args.forget:
            print("forgotten: whatever was said about page {0}".format(at))
        elif args.drop:
            fixes.append({"url": where, "drop": True, "made": time_stamp()})
            print("noted: no chapter starts at page {0}".format(at))
        else:
            fixes.append({"url": where, "label": args.label, "made": time_stamp()})
            print("noted: page {0} starts {1}".format(at, args.label))
    if fixes:
        block["fixes"] = fixes
    else:
        block.pop("fixes", None)
    stored = block.get("list") or []
    if stored or fixes:
        #with nothing worked out yet, the corrections are the whole of it: a comic whose site says nowhere
        #where its chapters start is chaptered by hand, one boundary at a time, and that is a source like
        #any other rather than something that has to wait for a rule to find nothing first.
        found, took, missed = apply_fixes([dict(chapter) for chapter in stored], pages, fixes)
        say_fixes(took, missed)
        chapters = settle_chapters(found, pages)
        block["list"] = [chapter_record(chapter) for chapter in chapters]
        block["checked"] = time_stamp()
        if not stored:
            block.setdefault("source", "hand")
        print()
        show_chapters(folder, chapters, pages)
    if args.forget or args.clear:
        print("  a correction taken back does not bring the old boundary back on its own. Run "
              "chapters.py chapters {0} --save to work them out afresh.".format(folder))
    write_metadata(folder, metadata)
    if not (stored and block.get("packed")):
        #nothing has been written for these chapters yet, so there is nothing to put right
        return 0
    if args.no_repack:
        print("  the chapter archives still hold the old boundaries: chapters.py pack {0}".format(folder))
        return 0
    #an archive holding a boundary this just corrected is a wrong archive, and a correction that leaves
    #one behind has not finished. only the archives whose contents changed are written again.
    print()
    return pack(folder, args)
