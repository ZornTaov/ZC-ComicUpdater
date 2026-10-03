#what a filename says about a page, from comiclib.pages: the name a page is saved under - what the site
#says the file is called - and that name read back as a page.
import pytest

from comiclib import pages as pages_module
from comiclib.pages import clear_unfinished, page_key, page_number, saved_name, write_page

PNG = b"\x89PNG\r\n\x1a\n" + b"rest of it"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 "


@pytest.mark.parametrize("src, name", [
    ("https://example.com/comics/0001.png", "0001.png"),
    #a name that says what it is is kept as it is: a jpg is a jpg, never a jpg with .png on the end
    ("https://example.com/comics/0002.jpg", "0002.jpg"),
    ("https://example.com/comics/moving.gif", "moving.gif"),
    ("https://example.com/comics/page.webp", "page.webp"),
    #a query string or a fragment is not part of the name
    ("https://example.com/comics/0003.png?v=2", "0003.png"),
    ("https://example.com/comics/0004.jpg#top", "0004.jpg"),
    #nothing to say what the file is, and nothing fetched to ask: the address is all there is
    ("https://example.com/comics/page-one", "page-one"),
    ("https://example.com/comic-image/1650564/?token=abc&expires=1", "1650564"),
    ("https://example.com/image.php?id=40", "image.php"),
], ids=["png", "jpg", "gif", "webp", "query", "fragment", "no extension", "id before a token", "script"])
def test_the_name_is_the_one_the_address_gives(src, name):
    assert saved_name(src) == name


def test_the_servers_own_filename_comes_first():
    headers = {"Content-Disposition": 'inline; filename="page-0042.webp"', "Content-Type": "image/webp"}
    assert saved_name("https://example.com/comic-image/42/?token=abc", headers, WEBP) == "page-0042.webp"


def test_an_encoded_filename_is_read_too():
    headers = {"Content-Disposition": "attachment; filename*=UTF-8''caf%C3%A9%20page.png"}
    assert saved_name("https://example.com/x", headers) == "café page.png"


def test_a_server_cannot_name_a_file_outside_the_folder():
    #only the last part of whatever path a header gives is a name
    headers = {"Content-Disposition": 'attachment; filename="../../etc/page.png"'}
    assert saved_name("https://example.com/x", headers) == "page.png"


def test_a_name_with_no_extension_takes_one_from_the_type_the_server_says():
    headers = {"Content-Type": "image/webp"}
    assert saved_name("https://example.com/comic-image/1650564/?token=abc", headers, WEBP) == "1650564.webp"


def test_and_failing_that_from_the_files_own_first_bytes():
    assert saved_name("https://example.com/comic-image/7/", {}, PNG) == "7.png"
    #a type the server gets wrong does not matter while the name already says what the file is
    assert saved_name("https://example.com/0001.jpg", {"Content-Type": "image/png"}, PNG) == "0001.jpg"


def test_a_name_no_filesystem_would_take_is_made_safe():
    headers = {"Content-Disposition": 'inline; filename="what?: a page*.png"'}
    assert saved_name("https://example.com/x", headers) == "what__ a page_.png"


def test_a_saved_name_reads_back_as_the_same_page():
    #numbered or not, the page a name was saved as is the page it reads as
    name = saved_name("https://example.com/comics/0042.png?cache=1")
    assert page_key("0042_" + name) == page_key(name)
    assert page_number("0042_" + name) == 42


def test_a_page_is_never_half_written_under_its_own_name(tmp_path, monkeypatch):
    #killed after writing but before moving it into place: whatever the page was before is still there,
    #whole, and the half-finished copy is only ever under the name that says so
    target = tmp_path / "0003_p3.jpg"
    target.write_bytes(b"the page as it was")

    def killed(*ignored):
        raise KeyboardInterrupt("stopped here")

    monkeypatch.setattr(pages_module.os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        write_page(str(target), b"a new copy of the page")
    assert target.read_bytes() == b"the page as it was"
    monkeypatch.undo()
    assert clear_unfinished(str(tmp_path)) == ["0003_p3.jpg.writing"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0003_p3.jpg"]


def test_a_page_saved_the_old_way_is_the_same_page_saved_now():
    #pages saved before names were taken as the site gives them had .png tacked on; they are still the page
    assert page_key("page.jpg.png") == page_key(saved_name("https://example.com/page.jpg"))


def test_a_folder_is_listed_once_with_every_files_size(tmp_path, monkeypatch):
    #one listing answers both what the files are and how big each is, on windows and linux alike; nothing
    #asks file by file, which on a network share was a round trip for every page of the comic
    (tmp_path / "0002_b.png").write_bytes(b"x" * 20)
    (tmp_path / "0001_a.jpg").write_bytes(b"x" * 10)
    (tmp_path / "notes.txt").write_bytes(b"x" * 5)
    (tmp_path / "extras.png").mkdir()
    asked = []
    monkeypatch.setattr(pages_module.os.path, "getsize", lambda path: asked.append(path) or 0)
    monkeypatch.setattr(pages_module.os.path, "isfile", lambda path: asked.append(path) or True)
    assert pages_module.sizes(str(tmp_path)) == {"0001_a.jpg": 10, "0002_b.png": 20, "notes.txt": 5}
    #a folder named like a page is not one
    assert pages_module.listing(str(tmp_path)) == ["0001_a.jpg", "0002_b.png"]
    assert not asked
    assert pages_module.sizes(str(tmp_path / "gone")) == {}
