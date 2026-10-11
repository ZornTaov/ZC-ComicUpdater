#covers: a page chosen in the reader, or a picture put in, for a comic or a folder, series or author; kept
#by the reader and written onto the shelf beside the comic's archive or in the folder, where other readers
#look - never into a comic's folder of pages - and a picture already on the shelf shown when nothing is chosen.
import io
import os

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
