#an archive the scraper never packed, holding pages that are not pictures: a video, a flash file, a note
#naming where a video lives. each is a page in its place - drawn as the scraper's stand-in would be, and
#the real thing there to be played - while a readme or a script beside the pages stays out.
import zipfile
import zlib

from conftest import png

from comicreader.sources import swf_shape

def swf(width, height, kind=b"FWS"):
    #a flash header: the frame rectangle in twips, as many bits per field as the largest needs
    fields = [0, width * 20, 0, height * 20]
    size = max(value.bit_length() for value in fields) + 1
    bits = "{0:05b}".format(size) + "".join("{0:0{1}b}".format(value, size) for value in fields)
    bits += "0" * (-len(bits) % 8)
    body = int(bits, 2).to_bytes(len(bits) // 8, "big") + b"\x00\x0c\x01\x00" + b"\x00" * 40
    if kind == b"CWS":
        body = zlib.compress(body)
    return kind + b"\x0a" + (8 + len(body)).to_bytes(4, "little") + body


SWF = swf(800, 200)
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


def test_every_page_is_the_right_shape_before_it_loads(library, client):
    #so scrolling through a comic never jumps as its pictures and players arrive: pictures measured from
    #their first bytes, flash from its own header, a video or a link to one as a wide screen
    unadopted(library, entries={"01.png": png(40, 60), "02.swf": swf(800, 200), "03.mp4": MP4,
                                "04.txt": b"Trailer https://youtu.be/abcdefghijk"})
    _, comic = opened(client)
    assert [(page[1], page[2]) for page in comic["pages"]] == [(40, 60), (800, 200), (1600, 900), (1600, 900)]


def test_a_flash_header_says_its_size_however_it_is_compressed():
    assert swf_shape(swf(550, 400)) == (550, 400)
    assert swf_shape(swf(800, 200, b"CWS")[:200]) == (800, 200)
    assert swf_shape(b"not flash at all") is None
    assert swf_shape(b"CWS\x0a\x00\x00\x00\x00garbage") is None


def test_a_page_read_before_adoption_is_the_same_page_after(library, client):
    #keyed as the scraper's stand-in for it would be, so a place kept survives the comic being adopted
    unadopted(library, entries={"0001.png": png(4, 4), "0002_clip.mp4": MP4})
    _, app = client()
    comic = next(iter(app.state.library.comics.values()))
    assert app.state.library.stream(comic)["pages"][1]["key"] == "clip.png"
