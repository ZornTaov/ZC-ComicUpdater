#an archive the scraper never packed, holding pages that are not pictures: a video, a flash file, a note
#naming where a video lives. each is a page in its place - drawn as the scraper's stand-in would be, and
#the real thing there to be played - while a readme or a script beside the pages stays out.
import zipfile

from conftest import png

SWF = b"FWS\x0a" + b"\x00" * 60
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 64


def unadopted(library, name="TheirComic.cbz", entries=None):
    path = library / name
    with zipfile.ZipFile(str(path), "w") as zf:
        for entry, body in (entries or {}).items():
            zf.writestr(entry, body)
    return path


def opened(client):
    api, app = client()
    comic = api.get("/api/library").json()["comics"][0]
    return api, api.get("/api/comics/{0}".format(comic["id"])).json()


def test_a_note_named_like_a_page_is_a_page_and_a_readme_is_not(library, client):
    unadopted(library, entries={
        "TheirComic/3854.png": png(4, 4), "TheirComic/3855.txt": b"Our trailerhttps://www.youtube.com/embed/abcdefghijk?feature=oembed",
        "TheirComic/3856.png": png(4, 4), "TheirComic/README.txt": b"Saved by hand. See https://example.com/",
        "TheirComic/mirror_their_comic.py": b"print('scraper')"})
    api, comic = opened(client)
    assert [page[4] for page in comic["pages"]] == [None, "link", None]
    said = api.get("/api/comics/{0}/pages/1/standin".format(comic["id"])).json()
    assert (said["kind"], said["address"], said["title"]) == \
        ("link", "https://www.youtube.com/embed/abcdefghijk?feature=oembed", "Our trailer")
    page = api.get("/api/comics/{0}/pages/1".format(comic["id"]))
    assert page.headers["content-type"] == "image/png" and page.content.startswith(b"\x89PNG"), \
        "shown as the scraper's stand-in where only a picture will do - a cover, a spread"


def test_flash_pages_in_folders_of_their_own_read_in_place(library, client):
    #a comic kept a folder per month, flash pages among the pictures
    unadopted(library, entries={"0104/010405.png": png(4, 4), "0104/010406.swf": SWF, "0104/010407.png": png(4, 4),
                                "0105/010501.swf": SWF})
    api, comic = opened(client)
    assert [page[4] for page in comic["pages"]] == [None, "flash", None, "flash"]
    said = api.get("/api/comics/{0}/pages/1/standin".format(comic["id"])).json()
    assert said["kind"] == "flash" and said["name"] == "010406.swf"
    assert api.get(said["url"]).content == SWF


def test_a_video_inside_an_archive_plays_and_seeks(library, client):
    unadopted(library, entries={"01.png": png(4, 4), "02.mp4": MP4})
    api, comic = opened(client)
    said = api.get("/api/comics/{0}/pages/1/standin".format(comic["id"])).json()
    assert said["kind"] == "video"
    part = api.get(said["url"], headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == MP4[100:200]
    assert part.headers["content-range"] == "bytes 100-199/{0}".format(len(MP4))
    tail = api.get(said["url"], headers={"Range": "bytes=-10"})
    assert tail.content == MP4[-10:]
    assert api.get(said["url"], headers={"Range": "bytes={0}-".format(len(MP4) + 5)}).status_code == 416
    assert api.get(said["url"]).content == MP4


def test_a_bonus_folder_beside_the_pages_is_not_read_as_pages(library, client):
    #an archive whose pages are at the top, with the original flash kept in a folder of its own as a bonus
    unadopted(library, entries={"01.png": png(4, 4), "02.png": png(4, 4),
                                "[B] Original Flash SWF/whole thing.swf": SWF})
    _, comic = opened(client)
    assert len(comic["pages"]) == 2


def test_a_page_read_before_adoption_is_the_same_page_after(library, client):
    #keyed as the scraper's stand-in for it would be, so a place kept survives the comic being adopted
    unadopted(library, entries={"0001.png": png(4, 4), "0002_clip.mp4": MP4})
    _, app = client()
    comic = next(iter(app.state.library.comics.values()))
    assert app.state.library.stream(comic)["pages"][1]["key"] == "clip.png"
