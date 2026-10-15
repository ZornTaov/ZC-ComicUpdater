#an archive zipped on a mac: the comic's folder, and a __MACOSX tree beside it holding a '._' file named for
#every page - the mac's own finder data, no picture at all. every reading of an archive someone else made
#leaves them out, so they are never counted, unpacked, kept as extras, or taken to mean the pages are spread
#over two folders.
import zipfile

from conftest import run

from comiclib import cbz
from comiclib.adopt.scan import list_pages
from comiclib.pages import mac_leftover
from comiclib.web.uploads import look_inside

FORK = b"\x00\x05\x16\x07" + b"\x00" * 324


def mac_zipped(path, folder="MyComic", pages=3):
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr(folder + "/", b"")
        zf.writestr("__MACOSX/._" + folder, FORK)
        for n in range(1, pages + 1):
            zf.writestr("{0}/{1:04d}.jpg".format(folder, n), "page {0}".format(n))
            zf.writestr("__MACOSX/{0}/._{1:04d}.jpg".format(folder, n), FORK)
    return path


def test_what_a_mac_adds_is_told_from_a_page():
    assert mac_leftover("__MACOSX/MyComic/._0001.jpg") and mac_leftover("__MACOSX/._MyComic")
    assert mac_leftover("MyComic/._0001.jpg") and mac_leftover("MyComic\\._0001.jpg")
    assert not mac_leftover("MyComic/0001.jpg") and not mac_leftover("MyComic/.hidden_page.jpg")


def test_an_upload_counts_only_the_pages_and_finds_their_folder(tmp_path):
    found = look_inside(str(mac_zipped(tmp_path / "MyComic.zip")))
    assert (found["pages"], found["inner"], found["left_out"]) == (3, "MyComic", 0)


def test_the_pages_of_a_mac_zipped_archive_are_counted_once(tmp_path):
    assert list_pages(str(mac_zipped(tmp_path / "MyComic.cbz"))) == ["0001.jpg", "0002.jpg", "0003.jpg"]


def test_pages_appended_go_under_the_folder_the_archive_keeps_them_in(tmp_path):
    archive = mac_zipped(tmp_path / "MyComic.cbz")
    with zipfile.ZipFile(str(archive)) as zf:
        assert cbz.archive_prefix(zf, str(tmp_path / "MyComic")) == "MyComic/"
        assert cbz.page_order(zf.namelist(), "") == [], "nothing at the top is a page"
        assert cbz.page_order(zf.namelist(), "MyComic/") == ["MyComic/0001.jpg", "MyComic/0002.jpg",
                                                             "MyComic/0003.jpg"]


def test_a_mac_zipped_archive_is_unpacked_and_adopted_without_them(library):
    (library / "CBZs" / "MyComic").mkdir()
    mac_zipped(library / "CBZs" / "MyComic" / "MyComic.cbz")
    done = run("adopt_comic.py", "CBZs/MyComic/MyComic.cbz", "--unpack-to", "Uncompressed/MyComic", "--ended",
               "--root", ".", cwd=library)
    assert done.returncode == 0, done.stdout[-600:]
    folder = library / "Uncompressed" / "MyComic"
    assert sorted(p.name for p in folder.iterdir() if p.suffix == ".jpg") == ["0001.jpg", "0002.jpg", "0003.jpg"]
