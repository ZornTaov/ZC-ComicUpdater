#the server as the web page uses it: the library with what is unread, a page's bytes cached for good once
#the page names its version, where a comic was read up to, and the real file behind a stand-in.
import base64

from conftest import comic_folder, page_names, png

from comiclib import cbz


def single(library, name="MyComic", pages=5, **options):
    folder = comic_folder(library, name, pages, **options)
    archive = library / "CBZs" / (name + ".cbz")
    cbz.write(str(archive), str(folder), page_names(folder))
    return folder, archive


def first(api):
    return api.get("/api/library").json()["comics"][0]


def test_the_library_says_what_is_unread_and_new(library, client):
    folder, archive = single(library)
    api, _ = client()
    comic = first(api)
    assert (comic["title"], comic["pages"], comic["unread"], comic["position"]) == ("MyComic", 5, 5, None)
    saved = api.put("/api/comics/{0}/progress".format(comic["id"]), json={"position": 4}).json()
    assert saved["position"] == 4 and saved["key"] == "page5.png"
    comic = first(api)
    assert (comic["unread"], comic["new"]) == (0, 0)

    for n in (6, 7):
        (folder / "{0:04d}_page{0}.png".format(n)).write_bytes(png(40, 60, n))
    cbz.append(str(archive), str(folder), page_names(folder))
    api.post("/api/scan")
    comic = first(api)
    assert (comic["pages"], comic["unread"], comic["new"], comic["position"]) == (7, 2, 2, 4)


def test_how_far_down_a_page_is_kept_with_the_place(library, client, tmp_path):
    single(library)
    api, _ = client()
    comic_id = first(api)["id"]
    api.put("/api/comics/{0}/progress".format(comic_id), json={"position": 2, "part": 0.375})
    details = api.get("/api/comics/{0}".format(comic_id)).json()
    assert (details["position"], details["part"]) == (2, 0.375)
    #nothing wild is kept
    api.put("/api/comics/{0}/progress".format(comic_id), json={"position": 2, "part": "nonsense"})
    assert api.get("/api/comics/{0}".format(comic_id)).json()["part"] == 0


def test_many_comics_are_marked_read_and_unread_at_once(library, client):
    #a folder or series from its menu: each read to its own last page, one gone since is passed over
    single(library, "MyComic", pages=5)
    single(library, "OtherComic", pages=3)
    api, _ = client()
    ids = [comic["id"] for comic in api.get("/api/library").json()["comics"]]
    marked = api.put("/api/progress", json={"comics": ids + ["gone"], "read": True}).json()
    assert marked["marked"] == 2
    comics = api.get("/api/library").json()["comics"]
    assert sorted((comic["position"], comic["unread"]) for comic in comics) == [(2, 0), (4, 0)]
    api.put("/api/progress", json={"comics": ids, "read": False})
    assert [comic["position"] for comic in api.get("/api/library").json()["comics"]] == [None, None]


def test_a_data_folder_from_before_gains_the_new_column(tmp_path):
    #progress kept by a reader from before "part" was a column is still read, and can be added to
    import sqlite3

    from comicreader.store import Store
    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE progress (series TEXT PRIMARY KEY, key TEXT, position INTEGER NOT NULL, "
                "seen INTEGER NOT NULL, updated REAL NOT NULL)")
    old.execute("INSERT INTO progress VALUES ('abc', 'page.png', 7, 10, 1.0)")
    old.commit()
    old.close()
    store = Store(str(path))
    assert store.progress("abc")["position"] == 7 and store.progress("abc")["part"] == 0
    assert store.save_progress("abc", "page.png", 8, 10, 0.5)["part"] == 0.5


def test_a_page_named_with_its_version_is_kept_for_good(library, client):
    single(library)
    api, _ = client()
    comic = api.get("/api/comics/{0}".format(first(api)["id"])).json()
    version, width, height, standin, media = comic["pages"][2]
    assert (width, height, standin, media) == (40, 60, 0, None)
    page = api.get("/api/comics/{0}/pages/2?v={1}".format(comic["id"], version))
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert "immutable" in page.headers["cache-control"]
    again = api.get("/api/comics/{0}/pages/2".format(comic["id"]), headers={"If-None-Match": page.headers["etag"]})
    assert again.status_code == 304
    #without the version it is asked about every time, since page 2 is not always the same page
    assert api.get("/api/comics/{0}/pages/2".format(comic["id"])).headers["cache-control"] == "no-cache"
    assert api.get("/api/comics/{0}/pages/99".format(comic["id"])).status_code == 404


def test_a_page_number_that_comes_to_mean_another_page_gets_another_address(library, client):
    #the archive unchanged, but the reader now counting a page it skipped before: every number after it means
    #a different picture, and a browser keeping pages for good by address must not show the old one
    folder, archive = single(library)
    api, app = client()
    comic = next(iter(app.state.library.comics.values()))
    before = app.state.library.stream(comic)["pages"]
    stream = app.state.library.stream(comic)
    shifted = [dict(page, entry="other-" + page["entry"]) for page in stream["pages"]]
    source = app.state.library.sources.cached(comic["sources"][0])
    app.state.library.sources.known[comic["sources"][0]] = dict(source, pages=[
        {k: v for k, v in page.items() if k not in ("source", "v")} for page in shifted])
    after = app.state.library.stream(comic)["pages"]
    assert all(old["v"] != new["v"] for old, new in zip(before, after))
    #and two pages of one archive never share an address's version
    assert len({page["v"] for page in before}) == len(before)


def test_a_cover_is_made_from_the_first_page(library, client):
    single(library)
    api, _ = client()
    cover = api.get("/api/comics/{0}/cover".format(first(api)["id"]))
    assert cover.status_code == 200 and cover.content[:3] == b"\xff\xd8\xff"


def test_a_stand_in_opens_the_video_it_stands_for_and_can_seek_in_it(library, client):
    video = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 4
    single(library, extra={"0006_clip.mp4": video})
    api, _ = client()
    comic = api.get("/api/comics/{0}".format(first(api)["id"])).json()
    assert comic["pages"][5][3] == 1
    said = api.get("/api/comics/{0}/pages/5/standin".format(comic["id"])).json()
    assert said["kind"] == "video" and said["name"] == "0006_clip.mp4"
    part = api.get(said["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == video[:10]
    assert api.get("/api/comics/{0}/pages/0/standin".format(comic["id"])).json() == {"kind": None}


def test_settings_are_kept_for_every_comic_and_for_one(library, client):
    single(library)
    api, _ = client()
    comic_id = first(api)["id"]
    api.put("/api/settings", json={"fit": "width", "direction": "ltr"})
    api.put("/api/comics/{0}/settings".format(comic_id), json={"direction": "rtl"})
    assert api.get("/api/settings").json() == {"fit": "width", "direction": "ltr"}
    assert api.get("/api/comics/{0}".format(comic_id)).json()["settings"] == {"direction": "rtl"}


def test_a_password_is_asked_for_everything_but_the_home_screen_icon(library, client):
    single(library)
    api, _ = client(password="hunter2")
    assert api.get("/api/library").status_code == 401
    good = base64.b64encode(b"anyone:hunter2").decode()
    bad = base64.b64encode(b"anyone:wrong").decode()
    assert api.get("/api/library", headers={"Authorization": "Basic " + bad}).status_code == 401
    assert api.get("/api/library", headers={"Authorization": "Basic " + good}).status_code == 200
    assert api.get("/manifest.webmanifest").status_code == 404, "not asked for a password, only not there"
