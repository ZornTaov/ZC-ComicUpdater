#one source of pages - an archive, or a folder of loose pages - as the reader turns through it: its pages
#in reading order, what its ComicInfo says of each, and the bytes of any one of them.
#
#the scraper adds to a single archive in place: a zip keeps its directory at the end, and an append writes
#the new pages over the old directory and a new directory after them. an archive read in that moment is
#not a zip at all, or is one whose directory is still being written. so an archive is read only when its
#size or time has changed, read again if it changed while being read, and anything that fails leaves the
#last good reading in place, to be tried again once the file has settled.
import collections
import json
import os
import posixpath
import threading
import xml.etree.ElementTree as ET
import zipfile

from comiclib import cbz, comicinfo
from comiclib.metadata import METADATA_FILE
from comiclib.pages import PAGE_TYPES, listing, page_key, reading_order
from comiclib.standin import address_in, flash_types, held_otherwise, link_types, stand_in, video_types

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp", ".bmp": "image/bmp", ".avif": "image/avif"}
#what a page held some other way can be, by the extension the scraper keeps it under
ORIGINALS = [".mp4", ".m4v", ".webm", ".mov", ".mkv", ".swf", ".txt", ".url", ".webloc"]
VIDEO_MEDIA = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
               ".mkv": "video/x-matroska", ".swf": "application/x-shockwave-flash"}


class Busy(Exception):
    #an archive being written as it was read, with no earlier reading of it to fall back on
    pass


def stamp(path):
    found = os.stat(path)
    return [found.st_size, found.st_mtime_ns]


def top_folder(entries):
    #archives made by Compress-Archive keep every entry under the comic's folder name; the ComicInfo is at
    #the top whatever the pages are under
    names = [entry for entry in entries if entry != comicinfo.NAME]
    if not names or not all('/' in name for name in names):
        return ''
    first = names[0].split('/', 1)[0] + '/'
    return first if all(name.startswith(first) for name in names) else ''


def about_from(text):
    #what an archive's ComicInfo says it is, beyond its pages: the chapter label a reader shows, which part
    #of the series it is, and the bookmarks it puts on pages
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    about = {tag.lower(): root.findtext(tag) for tag in ("Title", "Series", "Number", "Count", "Web")
             if root.findtext(tag)}
    about["bookmarks"] = {str(at): page.get("Bookmark") for at, page in enumerate(root.iter("Page"))
                          if page.get("Bookmark")}
    return about


def read_archive(path):
    before = stamp(path)
    with zipfile.ZipFile(path) as zf:
        infos = {info.filename: info for info in zf.infolist() if not info.is_dir()}
        prefix = top_folder(list(infos))
        order = cbz.page_order(list(infos), prefix)
        if not order:
            #pages spread over folders of someone else's making: every picture, by its path
            order = reading_order(None, [name for name in infos if PAGE_TYPES.search(name)])
        info_text = zf.read(comicinfo.NAME) if comicinfo.NAME in infos else None
        metadata = None
        for name in (prefix + METADATA_FILE, METADATA_FILE):
            if name in infos:
                try:
                    metadata = json.loads(zf.read(name).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass
                break
    if stamp(path) != before:
        raise Busy(path)
    said = comicinfo.pages_said(info_text) if info_text else []
    #believed only where it describes these very pages, as the scraper itself does
    if len(said) != len(order) or any(each["size"] != infos[entry].file_size for each, entry in zip(said, order)):
        said = [None] * len(order)
    pages = []
    for entry, each in zip(order, said):
        each = each or {}
        pages.append({"entry": entry, "key": page_key(posixpath.basename(entry)), "size": infos[entry].file_size,
                      "w": each.get("width"), "h": each.get("height"), "standin": bool(each.get("standin"))})
    return {"kind": "archive", "path": path, "stamp": before, "pages": pages,
            "about": about_from(info_text) if info_text else {}, "metadata": metadata}


def read_folder(path):
    #a comic kept only as loose pages, for one whose archives are turned off. a page held as a video or a
    #flash file is shown as the same stand-in its archive would hold
    before = stamp(path)
    pages = []
    for name in listing(path, others=True):
        standin = bool(held_otherwise(path, name))
        pages.append({"entry": name, "key": page_key(os.path.splitext(name)[0] + ".png" if standin else name),
                      "size": None, "w": None, "h": None, "standin": standin})
    return {"kind": "folder", "path": path, "stamp": before, "pages": pages, "about": {}, "metadata": None}


class Sources:
    #every source the reader has read, by path, kept as current as their files
    def __init__(self, store):
        self.store = store
        self.known = store.sources()
        self.lock = threading.Lock()
        #a few archives held open, so turning pages does not read a zip's whole directory for every one.
        #keyed by the reading they belong to, so an archive that has grown is opened afresh
        self.open = collections.OrderedDict()

    def get(self, path, kind="archive"):
        held = self.known.get(path)
        try:
            now = stamp(path)
        except OSError:
            return held
        if held is not None and held["stamp"] == now:
            return held
        try:
            fresh = (read_folder if kind == "folder" else read_archive)(path)
        except (Busy, zipfile.BadZipFile, OSError, KeyError, EOFError):
            if held is not None:
                return held
            raise Busy(path)
        with self.lock:
            self.known[path] = fresh
        self.store.save_source(fresh)
        return fresh

    def cached(self, path):
        return self.known.get(path)

    def page(self, source, entry):
        #the bytes of one page, and what kind of picture it is
        if source["kind"] == "folder":
            lines = held_otherwise(source["path"], entry)
            if lines:
                return stand_in(lines), "image/png"
            with open(os.path.join(source["path"], entry), "rb") as f:
                return f.read(), MEDIA.get(os.path.splitext(entry)[1].lower(), "application/octet-stream")
        handle = (source["path"], tuple(source["stamp"]))
        with self.lock:
            zf = self.open.pop(handle, None)
            if zf is None:
                zf = zipfile.ZipFile(source["path"])
            self.open[handle] = zf
            while len(self.open) > 8:
                _, oldest = self.open.popitem(last=False)
                oldest.close()
            body = zf.read(entry)
        return body, MEDIA.get(os.path.splitext(entry)[1].lower(), "application/octet-stream")


def original(folder, entry):
    #what a stand-in stands for: the video, flash file or note in the comic's own folder, found by the name
    #the stand-in was given - the original's, with .png in place of its extension. None when the folder no
    #longer has it, or never did
    if not folder:
        return None
    stem = os.path.splitext(posixpath.basename(entry))[0]
    for extension in ORIGINALS:
        name = stem + extension
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not held_otherwise(folder, name):
            continue
        if video_types.search(name):
            return {"kind": "video", "path": path, "media": VIDEO_MEDIA[extension], "name": name}
        if flash_types.search(name):
            return {"kind": "flash", "path": path, "media": VIDEO_MEDIA[extension], "name": name}
        if link_types.search(name):
            address, called = address_in(path)
            return {"kind": "link", "address": address, "title": called, "name": name}
    return None
