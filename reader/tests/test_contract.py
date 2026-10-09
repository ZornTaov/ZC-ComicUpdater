#what the reader relies on comiclib for, checked from the reader's side: if the scraper changes any of
#this, the reader's suite is where it shows. run it whenever a comiclib change is deployed.
import os
import subprocess
import sys
import zipfile

from conftest import comic_folder, page_names, png

from comiclib import cbz, comicinfo
from comiclib.pages import page_key, reading_order
from comicreader.sources import original, read_archive

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_the_modules_the_reader_imports_need_nothing_but_the_standard_library():
    #the reader's image carries no selenium and no requests, so importing these must not pull either in
    check = ("import sys; import comiclib.pages, comiclib.cbz, comiclib.comicinfo, comiclib.metadata, "
             "comiclib.standin; print(sorted(m for m in ('selenium', 'requests') if m in sys.modules))")
    done = subprocess.run([sys.executable, "-c", check], cwd=REPO, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout


def test_an_archive_reads_in_the_order_the_scraper_packed_it(library):
    folder = comic_folder(library, "MyComic", 12)
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder))
    read = [page["entry"] for page in read_archive(str(archive))["pages"]]
    assert read == reading_order(str(folder), [name for name in page_names(folder) if name.endswith(".png")])
    #a plain number sorts as a number: page 10 after page 9
    assert read[8:10] == ["0009_page9.png", "0010_page10.png"]


def test_unnumbered_pages_read_in_natural_order_as_the_folder_does(tmp_path):
    archive = tmp_path / "Loose.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        for name in ("page10.png", "page9.png", "page1.png"):
            zf.writestr(name, png(4, 4))
    assert [page["entry"] for page in read_archive(str(archive))["pages"]] == ["page1.png", "page9.png", "page10.png"]


def test_a_pages_key_survives_renumbering():
    #what progress is remembered by: a page renumbered, or given its doubled extension back, is the same page
    assert page_key("0742_a-page.png") == page_key("0743_a-page.png") == page_key("a-page.png.png")


def test_the_comicinfo_the_scraper_writes_is_what_the_reader_reads(library):
    folder = comic_folder(library, "MyComic", 3)
    archive = library / "CBZs" / "MyComic.cbz"
    about = comicinfo.about_chapter(str(folder), {"settings": {"ended": True}},
                                    {"number": 2, "label": "Second", "start_page": 1, "end_page": 3}, 4)
    cbz.write(str(archive), str(folder), page_names(folder), about=about)
    read = read_archive(str(archive))
    assert (read["about"]["title"], read["about"]["number"], read["about"]["count"]) == ("Second", "2", "4")
    assert read["about"]["bookmarks"] == {"0": "Second"}
    assert [(page["w"], page["h"]) for page in read["pages"]] == [(40, 60)] * 3


def test_a_stand_in_leads_back_to_what_it_stands_for(library):
    folder = comic_folder(library, "MyComic", 2, extra={"0003_clip.mp4": b"\x00\x00\x00\x18ftypmp42",
                                                       "0004.txt": b"Our trailer https://example.com/watch?v=1"})
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder))
    pages = read_archive(str(archive))["pages"]
    assert [page["standin"] for page in pages] == [False, False, True, True]
    video = original(str(folder), pages[2]["entry"])
    assert video["kind"] == "video" and video["name"] == "0003_clip.mp4"
    link = original(str(folder), pages[3]["entry"])
    assert (link["kind"], link["address"], link["title"]) == ("link", "https://example.com/watch?v=1", "Our trailer")
    assert original(str(folder), pages[0]["entry"]) is None
