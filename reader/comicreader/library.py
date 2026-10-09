#the comics in the library, each as one stream of pages however it is kept: a single archive that grows,
#one archive per chapter read one after another, or a folder of loose pages. a comic is a series, not an
#issue - which is the whole of what a reader built around issues gets wrong about a webcomic.
import hashlib
import os
import posixpath
import re
import threading
import time

from comiclib import cbz
from comiclib.metadata import METADATA_FILE, migrate, read as read_metadata
from comiclib.pages import sort_key
from comiclib.standin import held_otherwise

from comicreader.sources import ORIGINALS, Busy, Sources

#how packing names a chapter's archive: "<Comic> - c007 - <label>.cbz"
CHAPTER = re.compile(r"^(?P<series>.+?) - c(?P<number>\d+)(?: - (?P<label>.*))?\.cbz$", re.I)


def ident(text):
    #a comic's id, from where it is in the library, so it stays the same across scans and restarts
    return hashlib.sha1(text.replace(os.sep, "/").encode("utf-8")).hexdigest()[:12]


def walk(library, skip):
    #every comic folder (one holding the scraper's metadata) and every archive, in one pass. a comic
    #folder is not gone into further: whatever it keeps inside is its own
    comics, archives = [], []
    library = os.path.normpath(os.path.abspath(library))
    for current, dirs, files in os.walk(library):
        archives += [os.path.join(current, name) for name in files if name.lower().endswith(".cbz")]
        if METADATA_FILE in files and os.path.abspath(current) != os.path.abspath(library):
            comics.append(current)
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in skip)
    return comics, archives


def inside(library, path):
    #a path the metadata gives, relative to the library as the scraper stores them
    if not path:
        return None
    path = path.replace("/", os.sep)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(library, path))


#"The Title - by Someone", the way a shelf of archives from elsewhere is often named
BYLINE = re.compile(r"^(?P<title>.+?)\s+-\s+by\s+(?P<author>.+)$", re.I)


def named(stem):
    #a title and an author from an archive's file name: underscores were spaces before some tool saved it
    text = re.sub(r"\s+", " ", stem.replace("_", " ")).strip()
    found = BYLINE.match(text)
    if found:
        return found.group("title").strip(" -"), found.group("author").strip()
    return text, None


def listed_in(library, where, name):
    #the folder a comic is shown in, relative to the library, "" for the top. a folder holding nothing but
    #one comic's own archives is that comic, not a folder to go into first
    if os.path.basename(where).lower() == name.lower() and os.path.normpath(where) != library:
        where = os.path.dirname(where)
    relative = os.path.relpath(where, library).replace(os.sep, "/")
    return "" if relative == "." else relative


#a name's first number, and what comes before and after it: "Ch.01", "[10] NPC - A Very Bad Day", "001"
FIRST_NUMBER = re.compile(r"^(?P<before>\D*?)(?P<number>\d+)(?P<after>.*)$")


def numbered_runs(paths):
    #archives of one folder that are the parts of one series, told only by their names: three or more that
    #read the same up to their first number, each a different number, and those numbers near enough
    #consecutive - no more spread out than half as many again as there are, so a missing part or two is
    #fine. a folder of different comics that happen to share a word, or carry a year, is not one. answers
    #each archive in a run with its number
    by_start = {}
    for path in paths:
        found = FIRST_NUMBER.match(os.path.splitext(os.path.basename(path))[0])
        if found:
            by_start.setdefault(found.group("before").strip().lower(), []).append((int(found.group("number")), path))
    runs = {}
    for members in by_start.values():
        numbers = sorted(number for number, _ in members)
        if len(members) >= 3 and len(set(numbers)) == len(numbers) and \
                numbers[-1] - numbers[0] + 1 <= len(numbers) * 1.5:
            runs.update((path, number) for number, path in members)
    return runs


def chapter_order(path):
    found = CHAPTER.match(os.path.basename(path))
    return (int(found.group("number")) if found else 0, sort_key(os.path.basename(path)))


def gather(library, skip):
    #what the library holds, as comics: each with the sources it reads from, in order
    library = os.path.normpath(os.path.abspath(library))
    comics, archives = walk(library, skip)
    by_folder = {}
    for path in archives:
        by_folder.setdefault(os.path.dirname(path), []).append(path)
    claimed, found, unmatched = set(), [], []
    for folder in comics:
        metadata = read_metadata(folder)
        #a comic adopted long ago keeps the first way the metadata was written, its archive as archive_path;
        #read the way the scraper reads it, so the reader finds the same archive the scraper adds to
        metadata = migrate(metadata) or metadata
        settings = metadata.get("settings") or {}
        name = os.path.basename(folder)
        shelf = inside(library, (metadata.get("chapters") or {}).get("folder"))
        kind, sources = "folder", [folder]
        chapters = sorted((path for path in by_folder.get(shelf, []) if CHAPTER.match(os.path.basename(path))),
                          key=chapter_order) if shelf else []
        single = os.path.normpath(inside(library, settings.get("cbz_path")) or cbz.default_path(folder))
        if chapters:
            kind, sources = "chapters", chapters
            #the single archive it had before it was cut into chapters, if still on the shelf, is the same
            #comic: not another one to list beside it
            if os.path.isfile(single):
                claimed.add(single)
        elif settings.get("cbz") is not False and os.path.isfile(single):
            kind, sources = "archive", [single]
        if kind != "folder":
            claimed.update(sources)
        where = {"chapters": shelf, "archive": os.path.dirname(single)}.get(kind, os.path.dirname(folder))
        comic = {"id": ident(os.path.relpath(folder, library)), "title": name, "author": None, "kind": kind,
                 "sources": sources, "folder": folder, "ended": bool(settings.get("ended")),
                 "place": listed_in(library, where, name)}
        found.append(comic)
        #a comic kept without an archive on purpose looks for none: an archive of its name is someone else's
        if kind != "folder" or settings.get("cbz") is not False:
            unmatched.append(comic)
    #a comic whose metadata names an archive that is not there - the shelf sorted into folders by author
    #since it was written, or chapters packed somewhere the metadata never recorded - is read from what is
    #on the shelf under its own name, if exactly one thing is: one single archive, or one set of chapter
    #archives. two would be a guess, and it is read from its loose pages instead. a comic already read from
    #its chapters claims the single archive of its name too, the one it had before it was cut into them
    singles, sets = {}, {}
    for path in archives:
        if path in claimed:
            continue
        chapter = CHAPTER.match(os.path.basename(path))
        if chapter:
            sets.setdefault(chapter.group("series").lower(), {}).setdefault(os.path.dirname(path), []).append(path)
        else:
            singles.setdefault(os.path.splitext(os.path.basename(path))[0].lower(), []).append(path)
    for comic in unmatched:
        name = comic["title"].lower()
        single, chapters = singles.get(name, []), list(sets.get(name, {}).values())
        if comic["kind"] == "chapters":
            if len(single) == 1:
                claimed.add(single[0])
        elif comic["kind"] == "archive":
            #chapters packed beside the pages that the metadata never recorded: the single archive is what
            #the scraper goes on adding to, so it is what is read, and the chapters are not another comic
            if len(chapters) == 1:
                claimed.update(chapters[0])
        elif len(single) == 1:
            comic.update(kind="archive", sources=single,
                         place=listed_in(library, os.path.dirname(single[0]), comic["title"]))
            claimed.add(single[0])
        elif not single and len(chapters) == 1:
            ordered = sorted(chapters[0], key=chapter_order)
            comic.update(kind="chapters", sources=ordered,
                         place=listed_in(library, os.path.dirname(ordered[0]), comic["title"]))
            claimed.update(ordered)
    #archives no comic folder claims: a shelf of archives from somewhere else, or a comic whose loose
    #pages are gone. chapter archives of one series beside each other are read as one comic
    groups, loose = {}, {}
    for path in archives:
        if path in claimed:
            continue
        found_chapter = CHAPTER.match(os.path.basename(path))
        key = (os.path.dirname(path), found_chapter.group("series")) if found_chapter else (path, None)
        groups.setdefault(key, []).append(path)
        if not found_chapter:
            loose.setdefault(os.path.dirname(path), []).append(path)
    #archives of one folder numbered one after another are the parts of one series, named after the folder,
    #where no ComicInfo says otherwise. not at the top of the library, whose name says nothing about them
    runs = {}
    for where, paths in loose.items():
        if os.path.normpath(where) != library:
            runs.update(numbered_runs(paths))
    for (where, series), members in groups.items():
        if series:
            relative = os.path.join(os.path.relpath(where, library), series)
            title, author = named(series)
            found.append({"id": ident(relative), "title": title, "author": author, "kind": "chapters",
                          "sources": sorted(members, key=chapter_order), "folder": None, "ended": None,
                          "place": listed_in(library, where, series)})
        else:
            stem = os.path.splitext(os.path.basename(where))[0]
            title, author = named(stem)
            comic = {"id": ident(os.path.relpath(where, library)), "title": title, "author": author,
                     "kind": "archive", "sources": members, "folder": None, "ended": None,
                     "place": listed_in(library, os.path.dirname(where), title)}
            if where in runs:
                series = os.path.basename(os.path.dirname(where))
                comic.update(series=series, number=str(runs[where]))
                #a part named only by its number - 001.cbz - is called by its series and number
                if stem.strip().isdigit():
                    comic["title"] = "{0} {1}".format(series, runs[where])
            found.append(comic)
    return found


class Library:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.sources = Sources(store)
        self.comics = {}
        self.kept_otherwise = {}
        self.scanned = None
        self.scanning = threading.Lock()

    def scan(self):
        #the whole library looked over: which comics there are, and each archive read again where it has
        #changed since the last look. the reader keeps serving the last scan while this runs
        if not self.scanning.acquire(blocking=False):
            return False
        try:
            found = gather(self.config.library, self.config.skip)
            #which comics there are is known at once; each archive is then read again only where it changed,
            #and the last reading of it is served until then - a scan that has to read everything again, after
            #the reader learns to keep something new, is minutes on a big library, not minutes of nothing
            self.comics = {comic["id"]: comic for comic in found}
            for comic in found:
                for path in comic["sources"]:
                    try:
                        self.sources.get(path, "folder" if comic["kind"] == "folder" else "archive")
                    except Busy:
                        continue
            in_use = {path for comic in found for path in comic["sources"]}
            #an archive or folder gone from the library - deleted, renamed, given up for chapters - is
            #forgotten, not served from its last reading
            self.store.forget_sources(in_use)
            self.sources.forget(in_use)
            #what each comic holds now, against what the last scan saw: a comic that has grown is noted as
            #recently updated
            self.store.saw({comic["id"]: len(self.stream(comic)["pages"]) for comic in found})
            self.scanned = time.time()
            return True
        finally:
            self.scanning.release()

    def stream(self, comic, fresh=False):
        #the comic's pages from end to end, each knowing where it comes from, and where its chapters start.
        #fresh looks at each source's file first, so a comic opened while the scraper adds to it shows the
        #new pages without waiting for a scan
        kind = "folder" if comic["kind"] == "folder" else "archive"
        pages, chapters, versions, metadata, first = [], [], [], None, None
        #an archive the scraper packed before ComicInfo said which pages are stand-ins: the comic's folder
        #still holds what each stands for, under the same name
        originals = self.originals(comic["folder"]) if comic.get("folder") and kind == "archive" else set()
        for at, path in enumerate(comic["sources"]):
            try:
                source = self.sources.get(path, kind) if fresh else (self.sources.cached(path)
                                                                     or self.sources.get(path, kind))
            except Busy:
                source = self.sources.cached(path)
            if source is None:
                continue
            metadata = metadata or source.get("metadata")
            start = len(pages)
            about = source.get("about") or {}
            first = about if first is None else first
            if comic["kind"] == "chapters":
                label = about.get("title")
                if not label:
                    found = CHAPTER.match(os.path.basename(path))
                    label = (found.group("label") if found and found.group("label") else
                             "Chapter {0}".format(int(found.group("number")) if found else at + 1))
                chapters.append({"title": label, "start": start})
            else:
                for page, label in sorted(((int(n), label) for n, label in (about.get("bookmarks") or {}).items())):
                    chapters.append({"title": label, "start": start + page})
            version = "{0:x}{1:x}".format(*source["stamp"])[-12:]
            versions.append(version)
            for page in source["pages"]:
                #a page is fetched as /pages/<number>?v=..., and a browser keeps it for good. the number alone
                #can come to mean another page while the archive stays the same - a reader that learns to show
                #a comic's flash pages puts them among its pictures - so the version names the page itself
                #too, and an address is only ever one picture
                own = hashlib.sha1("{0}\0{1}".format(version, page["entry"]).encode("utf-8")).hexdigest()[:12]
                page = dict(page, source=at, v=own)
                if originals and not page["standin"] and page["entry"].lower().endswith(".png") and \
                        os.path.splitext(posixpath.basename(page["entry"]))[0].lower() in originals:
                    page["standin"] = True
                pages.append(page)
        ended = comic["ended"]
        if ended is None:
            ended = bool(((metadata or {}).get("settings") or {}).get("ended"))
        return {"pages": pages, "chapters": chapters, "ended": ended, "versions": versions, "about": first or {}}

    def originals(self, folder):
        #what a comic's folder keeps as a page no reader can show - a video, a flash file, a note naming where
        #a video is - by the name the stand-in drawn for it has, without its extension. looked at again only
        #when the folder has changed
        try:
            changed = os.stat(folder).st_mtime_ns
        except OSError:
            return set()
        kept = self.kept_otherwise.get(folder)
        if kept and kept[0] == changed:
            return kept[1]
        names = set()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if os.path.splitext(entry.name)[1].lower() in ORIGINALS and held_otherwise(folder, entry.name):
                        names.add(os.path.splitext(entry.name)[0].lower())
        except OSError:
            return set()
        self.kept_otherwise[folder] = (changed, names)
        return names

    def position(self, stream, progress):
        #where the reader is up to in a comic as it stands now. the page itself is what was remembered, not
        #its number: a comic renumbered, re-cut into chapters or with a page put in before it still opens on
        #the same page. the number is only for a page that is no longer there at all
        pages = stream["pages"]
        if not progress or not pages:
            return 0
        remembered = min(progress["position"], len(pages) - 1)
        if progress.get("key"):
            same = [at for at, page in enumerate(pages) if page["key"] == progress["key"]]
            if same:
                return min(same, key=lambda at: abs(at - progress["position"]))
        return remembered

    def summary(self, comic, progress, growth=None):
        stream = self.stream(comic)
        total = len(stream["pages"])
        at = self.position(stream, progress) if progress else None
        unread = total - at - 1 if at is not None else total
        about = stream["about"]
        #a single archive is an issue or a book, and its ComicInfo says which series and which one. a comic
        #in chapters is the series itself, whatever its first chapter's ComicInfo calls that chapter
        single = comic["kind"] == "archive"
        return {"id": comic["id"], "name": comic["title"],
                "title": (about.get("title") if single else None) or comic["title"],
                #a series is what a ComicInfo says one is - the issues of one comic, each its own archive - or,
                #where none does, a folder of archives numbered one after another (numbered_runs). never just a
                #shared name, which made two different comics into a series
                "series": ((about.get("series") or comic.get("series")) if single else None),
                "number": ((about.get("number") or comic.get("number")) if single else None),
                "volume": about.get("volume") if single else None,
                "year": about.get("year"), "author": about.get("writer") or about.get("penciller") or comic.get("author"),
                "place": comic.get("place", ""), "kind": comic["kind"], "pages": total,
                "position": at, "unread": unread, "ended": stream["ended"],
                "new": max(total - progress["seen"], 0) if progress else 0,
                #when a scan last saw it gain pages, and how many it gained then
                "grew": (growth or {}).get("grew"), "added": (growth or {}).get("added") or 0,
                "read": progress["updated"] if progress else None,
                #the cover is the first page, so it is that page's version: the same picture, the same address
                "chapters": len(stream["chapters"]), "cover": stream["pages"][0]["v"] if stream["pages"] else None,
                "updated": max((source["stamp"][1] for path in comic["sources"]
                                for source in [self.sources.cached(path)] if source), default=0) / 1e9}
