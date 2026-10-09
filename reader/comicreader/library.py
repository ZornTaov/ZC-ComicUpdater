#the comics in the library, each as one stream of pages however it is kept: a single archive that grows,
#one archive per chapter read one after another, or a folder of loose pages. a comic is a series, not an
#issue - which is the whole of what a reader built around issues gets wrong about a webcomic.
import hashlib
import os
import re
import threading
import time

from comiclib import cbz
from comiclib.metadata import METADATA_FILE, read as read_metadata
from comiclib.pages import sort_key

from comicreader.sources import Busy, Sources

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
    claimed, found = set(), []
    for folder in comics:
        metadata = read_metadata(folder)
        settings = metadata.get("settings") or {}
        name = os.path.basename(folder)
        shelf = inside(library, (metadata.get("chapters") or {}).get("folder"))
        kind, sources = "folder", [folder]
        chapters = sorted((path for path in by_folder.get(shelf, []) if CHAPTER.match(os.path.basename(path))),
                          key=chapter_order) if shelf else []
        single = os.path.normpath(inside(library, settings.get("cbz_path")) or cbz.default_path(folder))
        if chapters:
            kind, sources = "chapters", chapters
        elif settings.get("cbz") is not False and os.path.isfile(single):
            kind, sources = "archive", [single]
        if kind != "folder":
            claimed.update(sources)
        where = {"chapters": shelf, "archive": os.path.dirname(single)}.get(kind, os.path.dirname(folder))
        found.append({"id": ident(os.path.relpath(folder, library)), "title": name, "author": None, "kind": kind,
                      "sources": sources, "folder": folder, "ended": bool(settings.get("ended")),
                      "place": listed_in(library, where, name)})
    #archives no comic folder claims: a shelf of archives from somewhere else, or a comic whose loose
    #pages are gone. chapter archives of one series beside each other are read as one comic
    groups = {}
    for path in archives:
        if path in claimed:
            continue
        found_chapter = CHAPTER.match(os.path.basename(path))
        key = (os.path.dirname(path), found_chapter.group("series")) if found_chapter else (path, None)
        groups.setdefault(key, []).append(path)
    for (where, series), members in groups.items():
        if series:
            relative = os.path.join(os.path.relpath(where, library), series)
            title, author = named(series)
            found.append({"id": ident(relative), "title": title, "author": author, "kind": "chapters",
                          "sources": sorted(members, key=chapter_order), "folder": None, "ended": None,
                          "place": listed_in(library, where, series)})
        else:
            title, author = named(os.path.splitext(os.path.basename(where))[0])
            found.append({"id": ident(os.path.relpath(where, library)), "title": title, "author": author,
                          "kind": "archive", "sources": members, "folder": None, "ended": None,
                          "place": listed_in(library, os.path.dirname(where), title)})
    return found


class Library:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.sources = Sources(store)
        self.comics = {}
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
            self.store.forget_sources({path for comic in found for path in comic["sources"]})
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
                pages.append(dict(page, source=at, v=version))
        ended = comic["ended"]
        if ended is None:
            ended = bool(((metadata or {}).get("settings") or {}).get("ended"))
        return {"pages": pages, "chapters": chapters, "ended": ended, "versions": versions, "about": first or {}}

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

    def summary(self, comic, progress):
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
                "series": (about.get("series") if single else None) or (comic["title"] if not single else None),
                "number": about.get("number") if single else None, "volume": about.get("volume") if single else None,
                "year": about.get("year"), "author": about.get("writer") or about.get("penciller") or comic.get("author"),
                "place": comic.get("place", ""), "kind": comic["kind"], "pages": total,
                "position": at, "unread": unread, "ended": stream["ended"],
                "new": max(total - progress["seen"], 0) if progress else 0,
                "read": progress["updated"] if progress else None,
                "chapters": len(stream["chapters"]), "cover": stream["versions"][0] if stream["versions"] else None,
                "updated": max((source["stamp"][1] for path in comic["sources"]
                                for source in [self.sources.cached(path)] if source), default=0) / 1e9}
