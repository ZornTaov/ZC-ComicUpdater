#a comic brought in from somewhere else as one .zip or .cbz. it is received straight to disk a piece at a
#time, since a comic of thousands of pages is gigabytes; looked inside without unpacking, which reads only
#the archive's own list of what it holds; and then, once the reader has said where it goes - and, for pages
#nobody has adopted yet, where the comic is up to - unpacked into the library by a job in the queue, so it
#never lands in a folder a scrape is writing to.
import json
import os
import posixpath
import re
import secrets
import shutil
import time
import zipfile
from argparse import Namespace

from comiclib.adopt.adopting import adopt_one
from comiclib.adopt.scan import inspect as numbering, is_page
from comiclib.metadata import METADATA_FILE, migrate, now_stamp, read as read_metadata, write as write_metadata
from comiclib.web.adding import clean_folder, default_cbz, under_root

#inside the library, as dot-folders: the library scan skips anything whose name starts with a dot, so a
#comic half received, or one set aside for a newer copy, is never taken for a comic to update
UPLOADS = ".uploads"
REPLACED = ".replaced"
#read and written a megabyte at a time, so a file of gigabytes never sits in memory
CHUNK = 1 << 20
#what a browser may call a zip or a cbz. a page on another site cannot send any of these without the
#browser asking this server first, which it never agrees to - the same protection json gets
KINDS = ("application/zip", "application/x-zip-compressed", "application/x-cbz",
         "application/vnd.comicbook+zip", "application/octet-stream")
#room kept free beyond what is needed, so filling the disk is never the way an upload fails
MARGIN = 200 * 1024 * 1024
ADDRESS = re.compile(r"^https?://\S+$")


class Refused(Exception):
    #why an upload cannot go in, said so the reader knows what to change
    pass


def uploads_folder(root):
    return os.path.join(root, UPLOADS)


def receive(stream, length, root, filename):
    #the request body, written to the uploads folder as it arrives and looked inside once whole.
    #(status, answer)
    if length <= 0:
        return 411, {"error": "the upload did not say how big it is"}
    stem, ending = os.path.splitext(os.path.basename(filename or ""))
    ending = ending.lower()
    if ending not in (".zip", ".cbz"):
        return 415, {"error": "only a .zip or a .cbz can be uploaded; zip a folder of pages first"}
    #twice over: once as the upload, and again as the pages unpacked from it
    free = shutil.disk_usage(root).free
    if free < length * 2 + MARGIN:
        return 507, {"error": "not enough room in the library: this needs {0:.1f} GB to receive and unpack, and "
                              "{1:.1f} GB is free".format((length * 2 + MARGIN) / 1e9, free / 1e9)}
    folder = uploads_folder(root)
    os.makedirs(folder, exist_ok=True)
    upload = "{0}-{1}".format(time.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3))
    path = os.path.join(folder, upload + ending)
    left = length
    try:
        with open(path + ".writing", "wb") as out:
            while left > 0:
                piece = stream.read(min(CHUNK, left))
                if not piece:
                    break
                out.write(piece)
                left -= len(piece)
    except OSError as error:
        forget(path + ".writing")
        return 500, {"error": "could not write the upload: {0}".format(error)}
    if left:
        #a browser closed, or a connection dropped: what arrived is no use to anyone
        forget(path + ".writing")
        return 400, {"error": "the upload stopped {0:.0f}% of the way through; nothing was kept".format(
            100.0 * (length - left) / length)}
    os.replace(path + ".writing", path)
    try:
        found = look_inside(path)
    except (Refused, zipfile.BadZipFile, OSError, ValueError) as error:
        forget(path)
        return 400, {"error": "{0} cannot go in: {1}".format(filename, error)}
    found.update(id=upload, file=os.path.basename(filename), kind=ending[1:], bytes=length,
                 received=now_stamp(), suggested=found["suggested"] or stem)
    with open(os.path.join(folder, upload + ".json"), "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    return 200, found


def look_inside(path):
    #what an archive holds, from its own list of contents: its pages, how they are numbered, and whether
    #it is a comic this tool has already adopted. nothing is unpacked
    with zipfile.ZipFile(path) as archive:
        names = [info.filename.replace("\\", "/") for info in archive.infolist() if not info.is_dir()]
        unsafe = [name for name in names
                  if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/")]
        if unsafe:
            raise Refused("it holds a path that would land outside its own folder, {0}".format(unsafe[0]))
        pages = [name for name in names if is_page(name)]
        if not pages:
            raise Refused("there are no pages in it")
        #a comic here is one folder of pages. pages spread over several - a comic and its extras, kept apart
        #by whoever made the archive - have no single order to be read in, which is for the reader to settle
        folders = sorted({posixpath.dirname(name) for name in pages})
        if len(folders) > 1:
            raise Refused("its pages are in {0} different folders ({1}). Put them in one folder, or upload each "
                          "as a comic of its own".format(len(folders), ", ".join(f or "the top" for f in folders[:4])))
        inner = folders[0]
        kept = posixpath.join(inner, METADATA_FILE) if inner else METADATA_FILE
        metadata = None
        if kept in names:
            try:
                metadata = json.loads(archive.read(kept).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise Refused("its {0} cannot be read".format(METADATA_FILE))
    if metadata is not None and not isinstance(metadata, dict):
        raise Refused("its {0} is not a comic's settings".format(METADATA_FILE))
    found = numbering(sorted(posixpath.basename(name) for name in pages))
    others = [name for name in names if not is_page(name) and name != kept]
    return {
        "pages": found["count"], "numbering": found["style"], "last_number": found["last_number"],
        "inner": inner, "suggested": inner.rsplit("/", 1)[-1] if inner else "",
        #anything that is neither a page nor the settings stays behind: a copy of a script, a Thumbs.db
        "left_out": len(others), "left_out_sample": others[:5],
        "adopted": metadata is not None, "settings": summary(metadata) if metadata is not None else None,
    }


def summary(metadata):
    #what an adopted comic's settings say, in the current shape whatever shape the archive kept them in
    fresh = migrate(metadata) or metadata
    settings = fresh.get("settings") or {}
    history = fresh.get("history") or {}
    every = (fresh.get("chapters") or {}).get("every")
    return {"url": settings.get("url"), "increment": settings.get("increment"), "prefix": bool(settings.get("prefix")),
            "ended": bool(settings.get("ended")), "output": settings.get("output"),
            "cbz_path": settings.get("cbz_path"), "every": every,
            #a record of which page is which is never carried in an upload; said, so it is no surprise
            "index_cache": history.get("index_cache")}


def pending(root):
    #uploads received and not yet placed or discarded, newest first, so a page reloaded part way through
    #still offers them
    folder = uploads_folder(root)
    held = []
    if not os.path.isdir(folder):
        return held
    for name in sorted(os.listdir(folder), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                found = json.load(f)
        except (OSError, ValueError):
            continue
        #one already queued to go in is not offered again, or a page reloaded before the job ran could
        #queue it a second time
        if not found.get("queued"):
            held.append(found)
    return held


def mark_queued(root, upload, queued):
    #said in the upload's own record, so it outlives the page that queued it
    record = os.path.join(uploads_folder(root), upload + ".json")
    try:
        with open(record, encoding="utf-8") as f:
            found = json.load(f)
        found["queued"] = queued
        with open(record + ".writing", "w", encoding="utf-8") as f:
            json.dump(found, f, indent=1)
        os.replace(record + ".writing", record)
    except (OSError, ValueError):
        pass


def find(root, upload):
    #an upload by its id, which is checked to be one this module made before it goes near a path
    if not re.match(r"^\d{8}-\d{6}-[0-9a-f]{6}$", str(upload or "")):
        return None, None
    record = os.path.join(uploads_folder(root), upload + ".json")
    try:
        with open(record, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return None, None
    path = os.path.join(uploads_folder(root), upload + "." + found.get("kind", "zip"))
    return (found, path) if os.path.isfile(path) else (None, None)


def discard(root, upload):
    found, path = find(root, upload)
    if found is None:
        return 404, {"error": "no upload {0}".format(upload)}
    forget(path)
    forget(os.path.join(uploads_folder(root), upload + ".json"))
    return 200, {"discarded": upload}


def forget(path):
    try:
        os.remove(path)
    except OSError:
        pass


def whole_number(value, what):
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if not text.isdigit():
        raise Refused("{0} has to be a whole number".format(what))
    return int(text)


def plan(args, body):
    #what the reader asked for, checked before anything is queued, so a mistake is said at once rather
    #than in the log a minute later. (status, plan or answer)
    found, path = find(args.root, body.get("id"))
    if found is None:
        return 404, {"error": "that upload is no longer here; upload it again"}
    if found.get("queued"):
        return 409, {"error": "that upload is already queued to go in; Recent says how it went"}
    folder = clean_folder(str(body.get("folder") or ""))
    if folder is None:
        return 400, {"error": "say which folder it goes in, like MyComic or Series/MyComic"}
    as_archive = body.get("as") == "archive"
    archive = clean_folder(str(body.get("cbz") or "")) if body.get("cbz") else None
    if body.get("cbz") and archive is None:
        return 400, {"error": "the archive path is not a path inside the library"}
    pages_at = under_root(args.pages_folder, folder)
    archive_at = under_root(args.cbz_folder, archive or default_cbz(folder))
    if not archive_at.lower().endswith(".cbz"):
        archive_at += ".cbz"
    full = os.path.join(args.root, *pages_at.split("/"))
    archive_full = os.path.join(args.root, *archive_at.split("/"))
    replace = body.get("replace") is True
    taken = [where for where, there in ((pages_at, os.path.isdir(full) and os.listdir(full)),
                                        (archive_at, as_archive and os.path.exists(archive_full))) if there]
    if taken and not replace:
        return 409, {"error": "{0} is already in the library. Tick replace to set the one there aside (it is "
                              "kept, in {1}) and put this in its place".format(" and ".join(taken), REPLACED),
                     "exists": taken}
    chosen = {"id": found["id"], "path": path, "file": found["file"], "inner": found["inner"],
              "as_archive": as_archive, "pages_at": pages_at, "archive_at": archive_at, "replace": replace,
              "adopted": found["adopted"], "pages": found["pages"]}
    if found["adopted"]:
        return 200, chosen
    #adopting it here, which is adopt_comic.py with the form standing in for its arguments
    try:
        last_url = str(body.get("last_url") or "").strip()
        next_url = str(body.get("next_url") or "").strip()
        ended = body.get("ended") is True
        for given in (last_url, next_url):
            if given and not ADDRESS.match(given):
                raise Refused("{0} is not a full http(s) address".format(given))
        if last_url and next_url:
            raise Refused("give the last page you have or the first you do not, not both")
        if not (ended or last_url or next_url):
            raise Refused("say where the comic is up to - the last page you have, or the first you do not - "
                          "or that it has ended")
        increment = whole_number(body.get("increment"), "the page number to carry on from")
        every = whole_number(body.get("every"), "pages per part")
    except Refused as error:
        return 400, {"error": str(error)}
    chosen.update(last_url=last_url or None, next_url=next_url or None, ended=ended, increment=increment,
                  prefix=body.get("prefix") is True, every=every if every else None)
    return 200, chosen


def set_aside(full, root, stamp):
    #a folder or archive an upload replaces, moved into a dot-folder beside it rather than deleted
    aside = os.path.join(os.path.dirname(full), REPLACED)
    os.makedirs(aside, exist_ok=True)
    target = os.path.join(aside, "{0} {1}".format(os.path.basename(full), stamp))
    os.replace(full, target)
    return os.path.relpath(target, root).replace(os.sep, "/")


def unpack(path, inner, staging, cancel=None):
    #the pages and the settings, flat into staging. everything else in the archive stays behind
    os.makedirs(staging, exist_ok=True)
    done = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or posixpath.dirname(name) != inner:
                continue
            base = posixpath.basename(name)
            if not (is_page(base) or base == METADATA_FILE):
                continue
            with archive.open(info) as source, open(os.path.join(staging, base), "wb") as out:
                shutil.copyfileobj(source, out, CHUNK)
            done += 1
            if done % 500 == 0:
                print("  unpacked {0} file(s)".format(done), flush=True)
                if cancel is not None and cancel.is_set():
                    raise Refused("stopped part way through unpacking; nothing was put in the library")
    return done


def place(chosen, args, every_pages, cancel=None):
    #the job: unpack beside the library, set aside whatever it replaces, move it in, and adopt it when it
    #was not already. the outcome, said in a sentence
    root = args.root
    full = os.path.join(root, *chosen["pages_at"].split("/"))
    archive_full = os.path.join(root, *chosen["archive_at"].split("/"))
    staging = os.path.join(uploads_folder(root), chosen["id"] + ".unpacking")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    said = []
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    if chosen["as_archive"]:
        #kept whole on the shelf: only the settings, if it brought any, come out of it
        os.makedirs(staging)
        with zipfile.ZipFile(chosen["path"]) as archive:
            kept = posixpath.join(chosen["inner"], METADATA_FILE) if chosen["inner"] else METADATA_FILE
            if chosen["adopted"]:
                with open(os.path.join(staging, METADATA_FILE), "wb") as out:
                    out.write(archive.read(kept))
    else:
        print("Unpacking {0} ({1} pages) for {2}".format(chosen["file"], chosen["pages"], chosen["pages_at"]),
              flush=True)
        count = unpack(chosen["path"], chosen["inner"], staging, cancel)
        said.append("unpacked {0} file(s) into {1}".format(count, chosen["pages_at"]))

    #everything slow is done: from here on it is a few renames, so the library is never left half changed
    if os.path.isdir(full) and os.listdir(full):
        said.append("set the folder that was there aside as {0}".format(set_aside(full, root, stamp)))
    elif os.path.isdir(full):
        os.rmdir(full)
    if chosen["as_archive"] and os.path.exists(archive_full):
        said.append("set the archive that was there aside as {0}".format(set_aside(archive_full, root, stamp)))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    os.replace(staging, full)
    if chosen["as_archive"]:
        os.makedirs(os.path.dirname(archive_full), exist_ok=True)
        os.replace(chosen["path"], archive_full)
        said.insert(0, "put {0} on the shelf as {1}".format(chosen["file"], chosen["archive_at"]))

    if chosen["adopted"]:
        #its settings say where it lived before, which need not be where it lives now
        metadata = migrate(read_metadata(full)) or read_metadata(full)
        settings = metadata.setdefault("settings", {})
        settings["output"] = chosen["pages_at"]
        if chosen["as_archive"]:
            settings["cbz_path"] = chosen["archive_at"]
        metadata.setdefault("history", {})["uploaded"] = {"file": chosen["file"], "at": now_stamp()}
        write_metadata(full, metadata)
        said.append("kept the settings it came with")
    else:
        adopting = Namespace(path=full, root=root, last_url=chosen["last_url"], next_url=chosen["next_url"],
                             ended=chosen["ended"], increment=chosen["increment"], prefix=chosen["prefix"],
                             cbz_path=chosen["archive_at"] if chosen["as_archive"] else None, make_cbz=False,
                             dry_run=False, force=True)
        ok, outcome = adopt_one(adopting)
        if not ok:
            raise Refused("it was put in {0}, but adopting it failed: {1}".format(chosen["pages_at"], outcome))
        said.append("adopted it: {0}".format(outcome))
        if chosen["every"]:
            every_pages(full, chosen["every"])
            said.append("cut into parts of {0} pages".format(chosen["every"]))
    forget(chosen["path"])
    forget(os.path.join(uploads_folder(root), chosen["id"] + ".json"))
    return "; ".join(said)
