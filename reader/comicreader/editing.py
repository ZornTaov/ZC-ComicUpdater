#what the info page changes: what a comic is said to be, written where it will last. a comic the scraper keeps
#has it written into its metadata's info block - which the scraper writes into every ComicInfo it makes from
#then on - and its archives' ComicInfo brought up to it at once. an archive from somewhere else, with no
#metadata to keep it in, has its own ComicInfo changed, and everything else it says is left as it was.
#
#nothing is written while the scraper may be writing the same comic: during an update of the library, or
#while the comic's last run or its archives changed only moments ago
import calendar
import os
import time
import xml.etree.ElementTree as ET
import zipfile

from comiclib import cbz, comicinfo
from comiclib.metadata import METADATA_FILE, migrate, now_stamp, read as read_metadata, write_json

from comicreader.library import CHAPTER

#how long after the scraper last touched a comic it is left alone: a scrape writes its metadata after every
#page, and a slow site can take a while over one
QUIET = 300
#what update_comics holds while it updates the library
LOCK = ".update_comics.lock"
#the info block's keys, as ComicInfo calls them
TAGS = {"title": "Title", "series": "Series", "summary": "Summary", "year": "Year", "writer": "Writer",
        "penciller": "Penciller", "genre": "Genre", "tags": "Tags", "web": "Web"}
#the v2.1 schema's sequence, which a strict reader holds an archive to: a new element goes where it belongs
ORDER = ["Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber", "AlternateCount",
         "Summary", "Notes", "Year", "Month", "Day", "Writer", "Penciller", "Inker", "Colorist", "Letterer",
         "CoverArtist", "Editor", "Translator", "Publisher", "Imprint", "Genre", "Tags", "Web", "PageCount",
         "LanguageISO", "Format", "BlackAndWhite", "Manga", "Characters", "Teams", "Locations", "ScanInformation",
         "StoryArc", "StoryArcNumber", "SeriesGroup", "AgeRating", "Pages", "CommunityRating",
         "MainCharacterOrTeam", "Review", "GTIN"]


class Refused(Exception):
    #why the change was not made, said as what to do about it, with the status the page is answered with
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def stamp(path):
    found = os.stat(path)
    return (found.st_size, found.st_mtime_ns)


def ago(seconds):
    return "{0} seconds".format(int(seconds)) if seconds < 120 else "{0} minutes".format(int(seconds // 60))


def wait_for_quiet(library, paths, last_run):
    #refused while the scraper may be writing: an update of the whole library holds a lock, and a comic
    #updated on its own leaves its last run's time, and its archive's, only moments ago. an archive the
    #reader wrote itself is no sign of the scraper
    if os.path.exists(os.path.join(library.config.library, LOCK)):
        raise Refused(409, "The library is being updated right now. Try again once the update has finished.")
    now = time.time()
    if last_run:
        try:
            since = now - calendar.timegm(time.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ"))
        except (TypeError, ValueError):
            since = QUIET
        if since < QUIET:
            raise Refused(409, "This comic was being updated {0} ago and may still be. Try again in a few "
                               "minutes.".format(ago(max(since, 0))))
    for path in paths:
        try:
            found = stamp(path)
        except OSError:
            continue
        if library.written.get(path) == found:
            continue
        since = now - found[1] / 1e9
        if since < QUIET:
            raise Refused(409, "{0} changed {1} ago and may still be being written. Try again in a few "
                               "minutes.".format(os.path.basename(path), ago(max(since, 0))))


def writing(action):
    #a library mounted read-only refuses every write: said as what to change, not as an error
    try:
        return action()
    except OSError as error:
        if getattr(error, "errno", None) in (13, 30):
            raise Refused(503, "The reader cannot write to the library: it is mounted read-only, or not owned "
                               "by the reader's user. Mount it read-write to edit what a comic says.")
        raise


def retell(library, path, folder, about, keep_metadata):
    #a ComicInfo put on the end of the archive, as a scrape's append puts one: the pages stay where they are
    before = stamp(path)
    names = sorted(name for name in os.listdir(folder) if name != METADATA_FILE)
    change = cbz.planned(path, folder, names, (), about, adding=False)
    if not change["retold"]:
        return False
    if stamp(path) != before:
        raise Refused(409, "{0} changed while it was being looked at. Try again in a few minutes.".format(
            os.path.basename(path)))
    writing(lambda: cbz.apply(path, folder, change, metadata=keep_metadata))
    library.written[path] = stamp(path)
    return True


def chapter_archives(library, comic, metadata):
    #every chapter archive of a comic packed one per chapter, each with the chapter its metadata lists
    listed = {str(chapter.get("number")): chapter for chapter in (metadata.get("chapters") or {}).get("list") or []}
    out = []
    for each in library.comics.values():
        if each.get("parent") != comic["parent"]:
            continue
        found = CHAPTER.match(os.path.basename(each["sources"][0]))
        chapter = listed.get(str(int(found.group("number")))) if found else None
        if chapter:
            out.append((each["sources"][0], chapter))
    return out, len(listed)


def edit_scraped(library, comic, said, updated):
    folder = comic["folder"]
    path = os.path.join(folder, METADATA_FILE)
    metadata = read_metadata(folder)
    if not metadata:
        raise Refused(409, "This comic's metadata could not be read, so nothing was changed.")
    metadata = migrate(metadata) or metadata
    if updated is not None and metadata.get("updated") != updated:
        raise Refused(409, "This comic was changed since the page was opened. Reload it and make the change again.")
    runs = (metadata.get("history") or {}).get("runs") or []
    archives = []
    if comic.get("parent"):
        chapters, count = chapter_archives(library, comic, metadata)
        archives = [(archive, lambda m, chapter=chapter: comicinfo.about_chapter(folder, m, chapter, count), False)
                    for archive, chapter in chapters]
    elif comic["kind"] == "archive":
        archives = [(comic["sources"][0], lambda m: comicinfo.about_comic(folder, m), True)]
    wait_for_quiet(library, [archive for archive, _, _ in archives], runs[-1].get("updated") if runs else None)
    info = comicinfo.clean_info(said)
    if info:
        metadata["info"] = info
    else:
        metadata.pop("info", None)
    metadata["updated"] = now_stamp()
    writing(lambda: write_json(path, metadata))
    told = sum(1 for archive, about, whole in archives
               if os.path.isfile(archive) and retell(library, archive, folder, about(metadata), whole))
    return told


def edit_archive(library, comic, said, version):
    #an archive from somewhere else: its own ComicInfo, changed where the page changed it and nowhere else.
    #a field left empty is taken out
    path = comic["sources"][0]
    before = stamp(path)
    if version is not None and version != "{0:x}{1:x}".format(*before)[-12:]:
        raise Refused(409, "This archive was changed since the page was opened. Reload it and make the change again.")
    wait_for_quiet(library, [path], None)
    with zipfile.ZipFile(path) as zf:
        try:
            root = ET.fromstring(zf.read(comicinfo.NAME))
        except KeyError:
            root = ET.Element("ComicInfo")
        except ET.ParseError:
            raise Refused(409, "This archive's ComicInfo.xml cannot be read, so it was left as it is.")
    info = comicinfo.clean_info(said)
    for key, tag in TAGS.items():
        found = root.find(tag)
        value = info.get(key)
        if value is None:
            if found is not None:
                root.remove(found)
            continue
        if found is None:
            found = ET.Element(tag)
            rank = ORDER.index(tag)
            at = next((n for n, child in enumerate(root)
                       if child.tag in ORDER and ORDER.index(child.tag) > rank), len(root))
            root.insert(at, found)
        found.text = str(value)
    ET.indent(root, "  ")
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(path) as zf:
        try:
            if zf.read(comicinfo.NAME) == body:
                return 0
        except KeyError:
            pass
    if stamp(path) != before:
        raise Refused(409, "This archive changed while it was being looked at. Try again in a few minutes.")
    writing(lambda: cbz.apply(path, None, {"prefix": "", "added": [], "stale": [], "info": body}, metadata=False))
    library.written[path] = stamp(path)
    return 1


def edit(library, comic, body):
    said = body.get("info") or {}
    if not isinstance(said, dict):
        raise Refused(400, "info should be an object of what the comic is said to be.")
    if comic.get("folder"):
        return edit_scraped(library, comic, said, body.get("updated"))
    if comic["kind"] == "archive" and len(comic["sources"]) == 1:
        return edit_archive(library, comic, said, body.get("version"))
    raise Refused(409, "This comic is kept as chapter archives from somewhere else; each can be changed from "
                       "its own info page.")
