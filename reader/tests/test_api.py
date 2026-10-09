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


def test_a_page_named_with_its_version_is_kept_for_good(library, client):
    single(library)
    api, _ = client()
    comic = api.get("/api/comics/{0}".format(first(api)["id"])).json()
    version, width, height, standin = comic["pages"][2]
    assert (width, height, standin) == (40, 60, 0)
    page = api.get("/api/comics/{0}/pages/2?v={1}".format(comic["id"], version))
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert "immutable" in page.headers["cache-control"]
    again = api.get("/api/comics/{0}/pages/2".format(comic["id"]), headers={"If-None-Match": page.headers["etag"]})
    assert again.status_code == 304
    #without the version it is asked about every time, since page 2 is not always the same page
    assert api.get("/api/comics/{0}/pages/2".format(comic["id"])).headers["cache-control"] == "no-cache"
    assert api.get("/api/comics/{0}/pages/99".format(comic["id"])).status_code == 404


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
