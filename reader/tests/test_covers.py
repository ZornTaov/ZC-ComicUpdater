#covers: a page chosen in the reader, or a picture put in, for a comic or a folder, series or author; kept
#by the reader and written onto the shelf beside the comic's archive or in the folder, where other readers
#look - never into a comic's folder of pages - and a picture already on the shelf shown when nothing is chosen.
import http.server
import io
import os
import threading

import pytest
from PIL import Image

from conftest import comic_folder, page_names, png

from comiclib import cbz


def jpeg(width, height, colour):
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, "JPEG")
    return out.getvalue()


def single(library, name="MyComic", shelf="CBZs"):
    folder = comic_folder(library, name, 4)
    archive = library / shelf / (name + ".cbz")
    archive.parent.mkdir(parents=True, exist_ok=True)
    cbz.write(str(archive), str(folder), page_names(folder))
    return folder, archive


def comic_of(api, name):
    return next(comic for comic in api.get("/api/library").json()["comics"] if comic["name"] == name)


def colour_of(response):
    with Image.open(io.BytesIO(response.content)) as found:
        return found.convert("RGB").getpixel((found.width // 2, found.height // 2))


def test_a_page_chosen_as_a_comics_cover_is_its_cover_and_is_written_beside_its_archive(library, client):
    folder, archive = single(library)
    api, _ = client()
    comic = comic_of(api, "MyComic")
    first = comic["cover"]
    chosen = api.put("/api/covers", json={"target": "comic:" + comic["id"], "comic": comic["id"], "page": 2}).json()
    #the page itself, as the png it is: not made into anything else
    assert chosen["shelf"] == "CBZs/MyComic.png" and chosen["note"] is None
    beside = library / "CBZs" / "MyComic.png"
    assert beside.read_bytes() == (folder / "0003_page3.png").read_bytes()
    assert not (folder / "cover.png").exists()
    comic = comic_of(api, "MyComic")
    assert comic["cover"] != first and comic["coverChosen"]
    #the third page's picture, shaded as conftest shades page 3
    shown = api.get("/api/comics/{0}/cover?v={1}".format(comic["id"], comic["cover"]))
    assert shown.status_code == 200 and colour_of(shown)[0] in range(1, 6)
    #reset: back to the first page, and the picture the reader put on the shelf taken off it again
    reset = api.delete("/api/covers", params={"target": "comic:" + comic["id"]}).json()
    assert reset["v"] == first and not beside.exists()


def test_a_picture_already_beside_an_archive_is_its_cover_until_one_is_chosen(library, client):
    _, archive = single(library)
    (library / "CBZs" / "MyComic.png").write_bytes(png(30, 40, 200))
    api, _ = client()
    comic = comic_of(api, "MyComic")
    assert comic["cover"].startswith("s") and not comic["coverChosen"]
    shown = api.get("/api/comics/{0}/cover".format(comic["id"]))
    assert colour_of(shown)[0] == 200


def test_a_folders_own_picture_is_its_cover_by_any_name_other_readers_use(library, client):
    #folder.png and cover.jpg both, as other readers keep them; cover.jpg first where there are both
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    (library / "CBZs" / "SomeAuthor" / "folder.png").write_bytes(png(30, 40, 200))
    api, _ = client()
    assert colour_of(api.get("/api/covers", params={"target": "folder:CBZs/SomeAuthor"}))[0] == 200
    (library / "CBZs" / "SomeAuthor" / "cover.jpg").write_bytes(jpeg(30, 40, (10, 0, 0)))
    api.post("/api/scan")
    assert colour_of(api.get("/api/covers", params={"target": "folder:CBZs/SomeAuthor"}))[0] < 40


def test_a_folder_gets_a_cover_of_its_own_put_in_and_written_into_it(library, client):
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    api, _ = client()
    uploaded = api.put("/api/covers/upload", params={"target": "folder:CBZs/SomeAuthor"},
                       content=jpeg(300, 450, (10, 200, 30)))
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["shelf"] == "CBZs/SomeAuthor/cover.jpg"
    listed = api.get("/api/library").json()["covers"]
    assert listed["folder:CBZs/SomeAuthor"]["chosen"]
    shown = api.get("/api/covers", params={"target": "folder:CBZs/SomeAuthor"})
    assert colour_of(shown)[1] > 150
    #what is not a picture is refused, saying so
    refused = api.put("/api/covers/upload", params={"target": "folder:CBZs/SomeAuthor"}, content=b"not a picture")
    assert refused.status_code == 400 and "not a picture" in refused.json()["detail"]


def clear_png(width, height):
    #a picture drawn on a see-through background
    out = io.BytesIO()
    found = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    found.putpixel((width // 2, height // 2), (255, 0, 0, 255))
    found.save(out, "PNG")
    return out.getvalue()


def test_a_see_through_cover_stays_one_on_the_shelf_and_on_the_tile(library, client):
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    api, _ = client()
    target = {"target": "folder:CBZs/SomeAuthor"}
    #a jpeg first, then a png with a clear background put in its place
    api.put("/api/covers/upload", params=target, content=jpeg(300, 450, (10, 200, 30)))
    assert (library / "CBZs" / "SomeAuthor" / "cover.jpg").is_file()
    body = clear_png(300, 450)
    uploaded = api.put("/api/covers/upload", params=target, content=body).json()
    assert uploaded["shelf"] == "CBZs/SomeAuthor/cover.png"
    assert (library / "CBZs" / "SomeAuthor" / "cover.png").read_bytes() == body, "byte for byte as it came"
    assert not (library / "CBZs" / "SomeAuthor" / "cover.jpg").exists(), "the reader's own jpeg is taken off"
    shown = api.get("/api/covers", params=target)
    assert shown.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(shown.content)) as tile:
        assert tile.mode == "RGBA" and tile.getpixel((0, 0))[3] == 0, "the tile is see-through where the cover is"


@pytest.fixture
def web():
    #a site of two addresses on this machine: a picture, and a page that is not one
    body = clear_png(200, 300)

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            picture = self.path.endswith(".png")
            sent = body if picture else b"<html>not a picture</html>"
            self.send_response(200)
            self.send_header("Content-Type", "image/png" if picture else "text/html")
            self.send_header("Content-Length", str(len(sent)))
            self.end_headers()
            self.wfile.write(sent)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:{0}".format(server.server_address[1]), body
    server.shutdown()


def test_a_cover_from_a_web_address_is_fetched_once_and_kept_as_it_is(library, client, web):
    site, body = web
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    api, _ = client()
    target = "folder:CBZs/SomeAuthor"
    chosen = api.put("/api/covers/address", json={"target": target, "address": site + "/art/Cover.png"})
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["shelf"] == "CBZs/SomeAuthor/cover.png"
    assert (library / "CBZs" / "SomeAuthor" / "cover.png").read_bytes() == body, "byte for byte as the site has it"
    assert api.get("/api/library").json()["covers"][target]["chosen"]
    #a page that is not a picture, and an address that is not a web address, are refused saying so
    refused = api.put("/api/covers/address", json={"target": target, "address": site + "/a-page"})
    assert refused.status_code == 400 and "not a picture" in refused.json()["detail"]
    refused = api.put("/api/covers/address", json={"target": target, "address": "file:///etc/passwd"})
    assert refused.status_code == 400 and "web address" in refused.json()["detail"]


def test_a_cover_turns_a_quarter_at_a_time_from_the_picture_as_it_came(library, client):
    #a wide logo, see-through, made to stand up in a card shaped for a page
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    api, _ = client()
    target = {"target": "folder:CBZs/SomeAuthor"}
    body = clear_png(300, 100)
    api.put("/api/covers/upload", params=target, content=body)
    refused = api.put("/api/covers/turn", json={"target": "folder:CBZs/Nowhere", "by": 90})
    assert refused.status_code == 400 and "no chosen cover" in refused.json()["detail"]
    turned = api.put("/api/covers/turn", json=dict(target, by=90)).json()
    shelf = library / "CBZs" / "SomeAuthor" / "cover.png"
    with Image.open(str(shelf)) as now:
        assert now.size == (100, 300) and now.mode == "RGBA", "stood up, and still see-through"
        #the one red dot, a quarter turn clockwise: (150, 50) in a 300x100 picture lands at (100-1-50, 150)
        assert now.getpixel((49, 150))[:3] == (255, 0, 0)
    state = api.get("/api/covers/state", params=target).json()
    assert (state["turn"], state["how"], state["chosen"], state["shelf"]) == \
        (90, "picture", True, "CBZs/SomeAuthor/cover.png")
    shown = api.get("/api/covers", params=dict(target, v=turned["v"]))
    with Image.open(io.BytesIO(shown.content)) as tile:
        assert tile.height > tile.width, "the tile is turned too"
    #turned back round, it is the very picture that came
    api.put("/api/covers/turn", json=dict(target, by=-90))
    assert shelf.read_bytes() == body


def test_how_a_cover_fits_its_card_is_said_with_or_without_a_picture_chosen(library, client):
    single(library, "MyComic", "CBZs/SomeAuthor")
    single(library, "OtherComic", "CBZs/SomeAuthor")
    api, _ = client()
    comic = comic_of(api, "MyComic")
    assert comic["coverFit"] == "fill"
    #a comic's own first page, its whole width showing: no picture chosen, and none written anywhere
    state = api.put("/api/covers/fit", json={"target": "comic:" + comic["id"], "fit": "width"}).json()
    assert (state["fit"], state["chosen"]) == ("width", False)
    assert comic_of(api, "MyComic")["coverFit"] == "width" and not comic_of(api, "MyComic")["coverChosen"]
    #a folder's too, and a picture put in afterwards keeps the fit
    target = {"target": "folder:CBZs/SomeAuthor"}
    api.put("/api/covers/fit", json=dict(target, fit="height"))
    assert api.get("/api/library").json()["covers"]["folder:CBZs/SomeAuthor"] == \
        {"v": None, "chosen": False, "fit": "height"}, "its first comic's cover, fitted so"
    api.put("/api/covers/upload", params=target, content=clear_png(300, 100))
    assert api.get("/api/covers/state", params=target).json()["fit"] == "height"
    refused = api.put("/api/covers/fit", json=dict(target, fit="sideways"))
    assert refused.status_code == 400
    #reset puts all of it back
    api.delete("/api/covers", params=target)
    assert "folder:CBZs/SomeAuthor" not in api.get("/api/library").json()["covers"]


def test_a_comics_folder_of_pages_is_never_written_into(library, client):
    #a comic kept only as loose pages has nowhere on the shelf for a cover: it is the reader's alone
    comic_folder(library, "MyComic", 3, settings={"cbz": False})
    api, _ = client()
    comic = comic_of(api, "MyComic")
    chosen = api.put("/api/covers", json={"target": "comic:" + comic["id"], "comic": comic["id"], "page": 1}).json()
    assert chosen["shelf"] is None
    assert sorted(os.listdir(str(library / "Uncompressed" / "MyComic"))) == \
        ["0001_page1.png", "0002_page2.png", "0003_page3.png", "mirror_metadata.json"]
    #and a folder target naming a comic's own folder is refused a file too
    folder = api.put("/api/covers", json={"target": "folder:Uncompressed/MyComic", "comic": comic["id"], "page": 1})
    assert folder.json()["shelf"] is None and not (library / "Uncompressed" / "MyComic" / "cover.jpg").exists()


def test_a_series_cover_is_kept_by_the_reader_alone(library, client):
    single(library)
    api, _ = client()
    comic = comic_of(api, "MyComic")
    chosen = api.put("/api/covers", json={"target": "series:Some Series", "comic": comic["id"], "page": 0}).json()
    assert chosen["shelf"] is None and api.get("/api/library").json()["covers"]["series:Some Series"]["chosen"]
