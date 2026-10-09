#one source of pages - an archive, or a folder of loose pages - as the reader turns through it: its pages
#in reading order, what its ComicInfo says of each, and the bytes of any one of them.
#
#the scraper adds to a single archive in place: a zip keeps its directory at the end, and an append writes
#the new pages over the old directory and a new directory after them. an archive read in that moment is
#not a zip at all, or is one whose directory is still being written. so an archive is read only when its
#size or time has changed, read again if it changed while being read, and anything that fails leaves the
#last good reading in place, to be tried again once the file has settled.
import collections
import functools
import json
import lzma
import os
import posixpath
import threading
import xml.etree.ElementTree as ET
import zipfile
import zlib

from comiclib import comicinfo
from comiclib.metadata import METADATA_FILE
from comiclib.pages import PAGE_TYPES, listing, page_key, reading_order
from comiclib.standin import (NOTE_LIMIT, address_in, flash_types, held_otherwise, is_note_name, lines_for,
                              link_types, note_address, stand_in, video_types)

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp", ".bmp": "image/bmp", ".avif": "image/avif"}
#what a page held some other way can be, by the extension the scraper keeps it under
ORIGINALS = [".mp4", ".m4v", ".webm", ".mov", ".mkv", ".swf", ".txt", ".url", ".webloc"]
VIDEO_MEDIA = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
               ".mkv": "video/x-matroska", ".swf": "application/x-shockwave-flash"}


#what a reading of a source holds. a reading kept from an older reader, holding less, is read again once
FORMAT = 4


def head_of(zf, info):
    #the first bytes of an entry, for measuring it, without reading the whole page
    def read(n):
        with zf.open(info) as f:
            return f.read(n)
    return read


@functools.lru_cache(maxsize=64)
def drawn(lines):
    #a stand-in is drawn a dot at a time, which takes a moment; the same page asked for again is not redrawn
    return stand_in(list(lines))


def media_standin(page):
    #the picture shown for a page inside an archive that is not one, saying what it is - the scraper's own
    #stand-in, with the archive in place of the folder
    return drawn(tuple(lines_for(posixpath.basename(page["entry"]), page.get("address"), page.get("called"),
                                 where="this archive")))


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
    #of which series it is, who made it, and the bookmarks it puts on pages
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    about = {tag.lower(): root.findtext(tag).strip()
             for tag in ("Title", "Series", "Number", "Count", "Volume", "Year", "Writer", "Penciller", "Web")
             if (root.findtext(tag) or "").strip()}
    about["bookmarks"] = {str(at): page.get("Bookmark") for at, page in enumerate(root.iter("Page"))
                          if page.get("Bookmark")}
    return about


def media_kind(name):
    #a page that is not a picture: a recording, a flash file, or a note naming where a video is
    if video_types.search(name):
        return "video"
    if flash_types.search(name):
        return "flash"
    if is_note_name(name):
        return "link"
    return None


#what a video or a linked video is shown as before it has loaded: most are made for a 16:9 screen
WIDE = (1600, 900)


def swf_shape(head):
    #a flash movie's (width, height), from the frame rectangle that opens it - after an uncompressed,
    #zlib or LZMA header. a flash comic is often a wide strip, which it is shown as from the start
    try:
        kind = head[:3]
        if kind == b"FWS":
            body = head[8:]
        elif kind == b"CWS":
            body = zlib.decompressobj().decompress(head[8:], 64)
        elif kind == b"ZWS":
            #the LZMA properties come after a 4-byte length; lzma reads them as the start of an .lzma file
            #whose unknown size is written as all ones
            body = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(
                head[12:17] + b"\xff" * 8 + head[17:], 64)
        else:
            return None
        bits = int.from_bytes(body[:17], "big")
        size = bits >> (17 * 8 - 5)
        fields = []
        for at in range(4):
            shift = 17 * 8 - 5 - size * (at + 1)
            value = (bits >> shift) & ((1 << size) - 1)
            if value >> (size - 1):
                value -= 1 << size
            fields.append(value)
        width, height = (fields[1] - fields[0]) // 20, (fields[3] - fields[2]) // 20
        return (width, height) if width > 0 and height > 0 else None
    except (zlib.error, lzma.LZMAError, ValueError, IndexError, EOFError):
        return None


def media_shape(kind, read):
    #what a page that is not a picture is shown as, so its place is the right size before it loads
    if kind == "flash":
        return swf_shape(read(4096)) or (800, 600)
    return WIDE


def in_order(names, prefix):
    #the pages a reader turns through, as the scraper orders them: directly under the archive's one folder,
    #or - pages spread over folders of someone else's making - every page by its path
    here = {name[len(prefix):]: name for name in names if name.startswith(prefix) and "/" not in name[len(prefix):]}
    if here:
        return [here[name] for name in reading_order(None, list(here))]
    return reading_order(None, list(names))


def read_archive(path):
    #an archive made by anyone. one the scraper packed holds a drawn stand-in where a page is a video or
    #flash; one packed by hand, or by another tool, can hold the video, the flash file or the note itself,
    #and those are pages too - in their place, shown as what they are rather than skipped as gaps
    before = stamp(path)
    with zipfile.ZipFile(path) as zf:
        infos = {info.filename: info for info in zf.infolist() if not info.is_dir()}
        prefix = top_folder(list(infos))
        notes = {}
        for name, info in infos.items():
            #a note is a page only if it is named like one and says almost nothing but an address - the same
            #rule the scraper uses, so a comic's readme is never taken for page 102
            if media_kind(name) == "link" and info.file_size <= NOTE_LIMIT:
                address, called = note_address(zf.read(name).decode("utf-8", errors="replace"))
                if address:
                    notes[name] = (address, called)
        media = {name: media_kind(name) for name in infos
                 if media_kind(name) in ("video", "flash") or name in notes}
        order = in_order([name for name in infos if PAGE_TYPES.search(name) or name in media], prefix)
        #the pictures alone, in the order a ComicInfo the scraper wrote describes them
        pictures = [name for name in order if name not in media]
        #at the top, where the schema puts it; an archive made by another tool sometimes has it under its
        #folder, or spelled in another case
        named = comicinfo.NAME if comicinfo.NAME in infos else next(
            (name for name in infos if posixpath.basename(name).lower() == comicinfo.NAME.lower()
             and name.count("/") <= 1), None)
        info_text = zf.read(named) if named else None
        metadata = None
        for name in (prefix + METADATA_FILE, METADATA_FILE):
            if name in infos:
                try:
                    metadata = json.loads(zf.read(name).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass
                break
        said = comicinfo.pages_said(info_text) if info_text else []
        #believed only where it describes these very pages, as the scraper itself does
        if len(said) != len(pictures) or any(each["size"] != infos[entry].file_size for each, entry in zip(said, pictures)):
            said = []
        described = dict(zip(pictures, said))
        pages = []
        for entry in order:
            read = head_of(zf, infos[entry])
            if entry in media:
                #keyed as the stand-in the scraper would give it, so a place kept in a comic read before it
                #was adopted is still the same page after
                address, called = notes.get(entry, (None, None))
                width, height = media_shape(media[entry], read)
                pages.append({"entry": entry, "key": page_key(os.path.splitext(posixpath.basename(entry))[0] + ".png"),
                              "size": infos[entry].file_size, "w": width, "h": height, "standin": True,
                              "media": media[entry], "address": address, "called": called})
                continue
            #every page's size known before it is shown, so a comic scrolled through never jumps as pictures
            #arrive: from the ComicInfo where there is one, measured from the picture's first bytes where not
            each = described.get(entry) or {}
            shape = (each.get("width"), each.get("height")) if each.get("width") else comicinfo.measure(read)
            width, height = shape or (None, None)
            pages.append({"entry": entry, "key": page_key(posixpath.basename(entry)), "size": infos[entry].file_size,
                          "w": width, "h": height, "standin": bool(each.get("standin"))})
    if stamp(path) != before:
        raise Busy(path)
    return {"kind": "archive", "path": path, "stamp": before, "pages": pages, "format": FORMAT,
            "about": about_from(info_text) if info_text else {}, "metadata": metadata}


def read_folder(path):
    #a comic kept only as loose pages, for one whose archives are turned off. a page held as a video or a
    #flash file is shown as the same stand-in its archive would hold
    before = stamp(path)
    pages = []
    for name in listing(path, others=True):
        standin = bool(held_otherwise(path, name))

        def read(n, name=name):
            with open(os.path.join(path, name), "rb") as f:
                return f.read(n)
        shape = None if standin else comicinfo.measure(read)
        width, height = shape or (None, None)
        pages.append({"entry": name, "key": page_key(os.path.splitext(name)[0] + ".png" if standin else name),
                      "size": None, "w": width, "h": height, "standin": standin})
    return {"kind": "folder", "path": path, "stamp": before, "pages": pages, "about": {}, "metadata": None,
            "format": FORMAT}


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
        if held is not None and held["stamp"] == now and held.get("format") == FORMAT:
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

    def page(self, source, page):
        #the bytes of one page, and what kind of picture it is. a page that is not a picture is its stand-in
        entry = page["entry"]
        if page.get("media"):
            return media_standin(page), "image/png"
        if source["kind"] == "folder":
            lines = held_otherwise(source["path"], entry)
            if lines:
                return drawn(tuple(lines)), "image/png"
            with open(os.path.join(source["path"], entry), "rb") as f:
                return f.read(), MEDIA.get(os.path.splitext(entry)[1].lower(), "application/octet-stream")
        with self.lock:
            body = self.archive(source).read(entry)
        return body, MEDIA.get(os.path.splitext(entry)[1].lower(), "application/octet-stream")

    def archive(self, source):
        #held open, so turning pages does not read a zip's whole directory for every one. call under the lock
        handle = (source["path"], tuple(source["stamp"]))
        zf = self.open.pop(handle, None)
        if zf is None:
            zf = zipfile.ZipFile(source["path"])
        self.open[handle] = zf
        while len(self.open) > 8:
            _, oldest = self.open.popitem(last=False)
            oldest.close()
        return zf

    def read_range(self, source, entry, start, end):
        #part of an entry, for a video being played out of an archive: a player asks for the piece it is
        #about to show, and seeking in a stored entry reads only that piece
        with self.lock:
            zf = self.archive(source)
            with zf.open(entry) as f:
                f.seek(start)
                return f.read(end - start + 1)


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
