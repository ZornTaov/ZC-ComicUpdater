#the reader's server: the library as json, each page as its own bytes, and where each comic was read up to.
#the web page in web/ is everything else.
import base64
import hashlib
import hmac
import io
import mimetypes
import os
import posixpath
import re
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from comicreader.config import Config
from comicreader.editing import Refused, edit
from comicreader.info import describe
from comicreader.library import Library
from comicreader.sources import VIDEO_MEDIA, Busy, original
from comicreader.store import Store

#Ruffle's WebAssembly, which a browser compiles as it arrives only when it is sent as what it is - windows
#does not always know the type
mimetypes.add_type("application/wasm", ".wasm")

#a page asked for with the version of the archive it came from never changes, so the browser keeps it as
#long as it likes: turning back to a page is then instant, with no request at all
FOREVER = "private, max-age=31536000, immutable"
THUMB = (360, 540)


def create_app(config=None, scan_in_background=True):
    config = config or Config.from_env()
    store = Store(os.path.join(config.data, "reader.db"))
    library = Library(config, store)
    app = FastAPI(title="Comic reader", docs_url=None, redoc_url=None)
    app.state.library = library
    app.state.store = store
    app.state.config = config

    @app.middleware("http")
    async def password(request: Request, call_next):
        #the same as the scraper's web page: basic auth, any user name, one password. the manifest and icon
        #stay open, since a phone fetches them for the home screen without asking first
        if config.password and request.url.path not in ("/manifest.webmanifest", "/icon.svg"):
            given = request.headers.get("authorization", "")
            ok = False
            if given.startswith("Basic "):
                try:
                    _, _, secret = base64.b64decode(given[6:]).decode("utf-8").partition(":")
                    ok = hmac.compare_digest(secret, config.password)
                except (ValueError, UnicodeDecodeError):
                    ok = False
            if not ok:
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="reader"'})
        return await call_next(request)

    def comic_or_404(comic_id):
        comic = library.comics.get(comic_id)
        if comic is None:
            raise HTTPException(404, "no comic {0}; the library may not have been scanned yet".format(comic_id))
        return comic

    @app.get("/api/library")
    def everything():
        progress = store.every_progress()
        growth = store.growth()
        return {"scanned": library.scanned,
                "comics": sorted((library.summary(comic, progress.get(comic["id"]), growth.get(comic["id"]))
                                  for comic in library.comics.values()), key=lambda each: each["title"].lower())}

    @app.post("/api/scan")
    def scan():
        started = library.scan()
        return {"scanned": library.scanned, "started": started}

    @app.get("/api/comics/{comic_id}")
    def comic_details(comic_id: str):
        comic = comic_or_404(comic_id)
        stream = library.stream(comic, fresh=True)
        progress = store.progress(comic_id)
        return {"id": comic_id, "title": comic["title"], "kind": comic["kind"], "ended": stream["ended"],
                "position": library.position(stream, progress), "seen": progress["seen"] if progress else 0,
                "part": progress["part"] if progress else 0,
                "chapters": stream["chapters"],
                #kept short: a comic of thousands of pages is one request, opened every time it is read
                #the fifth is what a page held inside the archive as something other than a picture is
                "pages": [[page["v"], page["w"], page["h"], 1 if page["standin"] else 0, page.get("media")]
                          for page in stream["pages"]],
                "settings": store.settings("comic:" + comic_id),
                #the parts either side of it in its series, for reading on past either end
                **library.neighbours.get(comic_id, {"previous": None, "next": None})}

    @app.get("/api/comics/{comic_id}/info")
    def comic_info(comic_id: str):
        return describe(library, comic_or_404(comic_id))

    @app.put("/api/comics/{comic_id}/info")
    async def save_comic_info(comic_id: str, request: Request):
        comic = comic_or_404(comic_id)
        try:
            told = edit(library, comic, await request.json())
        except Refused as refused:
            raise HTTPException(refused.status, str(refused))
        return dict(describe(library, comic), told=told)

    def page_of(comic_id, n):
        comic = comic_or_404(comic_id)
        stream = library.stream(comic)
        if not 0 <= n < len(stream["pages"]):
            stream = library.stream(comic, fresh=True)
            if not 0 <= n < len(stream["pages"]):
                raise HTTPException(404, "{0} has {1} pages".format(comic["title"], len(stream["pages"])))
        page = stream["pages"][n]
        source = library.sources.cached(comic["sources"][page["source"]])
        if source is None:
            raise HTTPException(503, "that archive has not been read yet; try again")
        return comic, page, source

    @app.get("/api/comics/{comic_id}/pages/{n}")
    def page(comic_id: str, n: int, request: Request, v: str = ""):
        comic, each, source = page_of(comic_id, n)
        tag = '"{0}-{1}"'.format(each["v"], hashlib.sha1(each["entry"].encode("utf-8")).hexdigest()[:10])
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
        try:
            body, media = library.sources.page(source, each)
        except (Busy, OSError, KeyError) as error:
            #the archive is being added to this moment; the page asks again shortly
            raise HTTPException(503, "could not read the page just now ({0}); try again".format(error))
        return Response(body, media_type=media,
                        headers={"ETag": tag, "Cache-Control": FOREVER if v == each["v"] else "no-cache"})

    @app.get("/api/comics/{comic_id}/pages/{n}/standin")
    def standin(comic_id: str, n: int):
        #what a page standing in for a video, a flash page or a link is standing in for, so tapping it can
        #open the real thing
        comic, each, _ = page_of(comic_id, n)
        name = posixpath.basename(each["entry"])
        url = "/api/comics/{0}/pages/{1}/original".format(comic_id, n)
        #the thing itself, inside an archive someone else made
        if each.get("media") == "link":
            return {"kind": "link", "address": each["address"], "title": each.get("called"), "name": name}
        if each.get("media"):
            return {"kind": each["media"], "name": name, "url": url}
        #or kept in the comic's folder, behind a stand-in the scraper drew
        found = original(comic["folder"], each["entry"]) if each["standin"] or comic["folder"] else None
        if not found:
            return {"kind": None}
        if found["kind"] == "link":
            return {"kind": "link", "address": found["address"], "title": found["title"], "name": found["name"]}
        return {"kind": found["kind"], "name": found["name"],
                "url": "/api/comics/{0}/pages/{1}/original".format(comic_id, n)}

    @app.get("/api/comics/{comic_id}/pages/{n}/original")
    def original_file(comic_id: str, n: int, request: Request):
        comic, each, source = page_of(comic_id, n)
        if each.get("media") in ("video", "flash") and source["kind"] == "archive":
            extension = os.path.splitext(each["entry"])[1].lower()
            return ranged(request, each["size"], lambda start, end: library.sources.read_range(
                source, each["entry"], start, end), VIDEO_MEDIA.get(extension, "application/octet-stream"))
        found = original(comic["folder"], each["entry"])
        if not found or found["kind"] == "link":
            raise HTTPException(404, "no original kept for that page")
        #a file response answers range requests, which a video needs to seek
        return FileResponse(found["path"], media_type=found["media"], filename=found["name"])

    @app.get("/api/comics/{comic_id}/cover")
    def cover(comic_id: str, v: str = ""):
        comic, each, source = page_of(comic_id, 0)
        cached = os.path.join(config.data, "covers", "{0}-{1}.jpg".format(comic_id, each["v"]))
        if not os.path.isfile(cached):
            try:
                body, _ = library.sources.page(source, each)
                made = thumbnail(body)
            except Exception as error:  # noqa: BLE001 - a picture Pillow cannot open is a missing cover
                raise HTTPException(404, "no cover: {0}".format(error))
            os.makedirs(os.path.dirname(cached), exist_ok=True)
            with open(cached + ".writing", "wb") as f:
                f.write(made)
            os.replace(cached + ".writing", cached)
        return FileResponse(cached, media_type="image/jpeg", headers={"Cache-Control": FOREVER if v else "no-cache"})

    @app.put("/api/comics/{comic_id}/progress")
    async def save_progress(comic_id: str, request: Request):
        comic = comic_or_404(comic_id)
        body = await request.json()
        stream = library.stream(comic)
        if not stream["pages"]:
            raise HTTPException(409, "the comic has no pages to be up to")
        at = max(0, min(int(body.get("position", 0)), len(stream["pages"]) - 1))
        try:
            #how far down the page, as a share of it; a little before its top or well past its end is fine - the
            #last pages of a comic can never reach the top of the screen - but nothing wilder is kept
            part = max(-50.0, min(50.0, float(body.get("part") or 0)))
        except (TypeError, ValueError):
            part = 0.0
        saved = store.save_progress(comic_id, stream["pages"][at]["key"], at, len(stream["pages"]), part)
        return dict(saved, position=at)

    @app.delete("/api/comics/{comic_id}/progress")
    def forget_progress(comic_id: str):
        comic_or_404(comic_id)
        store.forget_progress(comic_id)
        return {"ok": True}

    @app.put("/api/progress")
    async def save_many(request: Request):
        #a whole folder or series marked at once, or every comic up to one: each read to its last page, or its
        #place forgotten. one gone since the page was drawn, or with no pages yet, is passed over rather than
        #failing the rest
        body = await request.json()
        read, marked = bool(body.get("read")), 0
        for comic_id in body.get("comics") or []:
            comic = library.comics.get(comic_id)
            if comic is None:
                continue
            if not read:
                store.forget_progress(comic_id)
            else:
                pages = library.stream(comic)["pages"]
                if not pages:
                    continue
                store.save_progress(comic_id, pages[-1]["key"], len(pages) - 1, len(pages))
            marked += 1
        return {"marked": marked}

    @app.get("/api/settings")
    def global_settings():
        return store.settings("global")

    @app.put("/api/settings")
    async def save_global_settings(request: Request):
        store.save_settings("global", await request.json())
        return store.settings("global")

    @app.put("/api/comics/{comic_id}/settings")
    async def save_comic_settings(comic_id: str, request: Request):
        comic_or_404(comic_id)
        store.save_settings("comic:" + comic_id, await request.json())
        return store.settings("comic:" + comic_id)

    @app.get("/api/health")
    def health():
        return JSONResponse({"comics": len(library.comics), "scanned": library.scanned})

    if os.path.isdir(config.web):
        app.mount("/", StaticFiles(directory=config.web, html=True), name="web")

    if scan_in_background:
        threading.Thread(target=keep_scanning, args=(library, config.scan_minutes), daemon=True).start()
    return app


#the most of a video sent for one request: a player asks again for the next piece as it plays
PIECE = 4 << 20
RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def ranged(request, size, read, media_type):
    #a file inside an archive, sent a piece at a time as a video player asks for it. a player that asks for
    #the whole of it is sent it whole
    asked = RANGE.match(request.headers.get("range", "").strip())
    if not asked or (asked.group(1) == "" and asked.group(2) == ""):
        return Response(read(0, size - 1) if size else b"", media_type=media_type, headers={"Accept-Ranges": "bytes"})
    if asked.group(1) == "":
        start, end = max(size - int(asked.group(2)), 0), size - 1
    else:
        start = int(asked.group(1))
        end = int(asked.group(2)) if asked.group(2) else size - 1
    end = min(end, size - 1, start + PIECE - 1)
    if start >= size or start > end:
        return Response(status_code=416, headers={"Content-Range": "bytes */{0}".format(size)})
    return Response(read(start, end), status_code=206, media_type=media_type,
                    headers={"Accept-Ranges": "bytes", "Content-Range": "bytes {0}-{1}/{2}".format(start, end, size)})


def keep_scanning(library, minutes):
    while True:
        try:
            library.scan()
        except Exception as error:  # noqa: BLE001 - one bad scan must not stop the next
            print("scan failed: {0}".format(error), flush=True)
        time.sleep(max(minutes, 1) * 60)


def thumbnail(body):
    #a cover for the library shelf: the first page, small. Pillow, since a cover has to be scaled well and
    #this is the reader's own image, not the scraper's
    from PIL import Image
    with Image.open(io.BytesIO(body)) as picture:
        picture = picture.convert("RGB")
        picture.thumbnail(THUMB)
        out = io.BytesIO()
        picture.save(out, "JPEG", quality=82)
    return out.getvalue()
