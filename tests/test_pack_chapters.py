#packing a comic one archive per chapter, beside the single archive it had: named to sort, holding what
#each chapter holds, rewritten only when something in it changed, and checked before the single archive is
#given up.
import json
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

from conftest import read_meta, run, write_index, write_meta

PAGES = 12
FIRST = "Tiny - c001 - Chapter 1.cbz"
SECOND = "Tiny - c002 - Arc 2 - Trouble Part 1 2.cbz"
THIRD = "Tiny - c003 - Chapter 3.cbz"
CHAPTERS = [{"number": 1, "label": "Chapter 1", "start_page": 1, "end_page": 4, "pages": 4,
             "start_url": "https://x.test/p1", "start_file": "0001.png"},
            {"number": 2, "label": "Arc 2 - Trouble: Part 1/2", "start_page": 5, "end_page": 9, "pages": 5,
             "start_url": "https://x.test/p5", "start_file": "0006.png"},
            {"number": 3, "label": "Chapter 3", "start_page": 10, "end_page": 12, "pages": 3,
             "start_url": "https://x.test/p10", "start_file": "0010.png"}]


class Tiny:
    def __init__(self, library, comic):
        self.library = library
        self.comic = comic
        self.single = library / "CBZs" / "Group" / "Tiny.cbz"
        self.out = library / "CBZs" / "Group" / "Tiny"

    def pack(self, *extra):
        return run("chapters.py", "pack", self.comic, "--root", self.library, *extra)

    def made(self):
        return sorted(os.listdir(str(self.out))) if self.out.is_dir() else []

    def stamps(self):
        return {name: os.path.getmtime(str(self.out / name)) for name in self.made()}


@pytest.fixture
def tiny(library, chapters):
    comic = library / "Uncompressed" / "Group" / "Tiny"
    comic.mkdir(parents=True)
    (library / "CBZs" / "Group").mkdir()
    for n in range(1, PAGES + 1):
        #page 5 is a flash page, and was never saved here
        if n != 5:
            (comic / "{0:04d}.png".format(n)).write_bytes(bytes([n]) * (100 * n))
    write_meta(comic, {"schema": 2, "settings": {"url": "https://x.test/p12", "output": "Uncompressed/Group/Tiny",
                                                 "cbz_path": "CBZs/Group/Tiny.cbz", "cbz": True, "increment": 12},
                       "history": {"runs": []},
                       "chapters": {"source": "archive", "list": CHAPTERS}})
    cache = chapters.index_path(str(comic))
    write_index(cache, [{"n": n, "url": "https://x.test/p{0}".format(n), "src": "https://x.test/i{0}.png".format(n),
                         "file": "{0}.png".format(n), "bytes": 100 * n} for n in range(1, PAGES + 1)])
    with open(cache.replace(".jsonl", ".align.json"), "w") as f:
        json.dump({"comic": str(comic), "settled": True,
                   "pages": [{"n": n, "url": "https://x.test/p{0}".format(n),
                              "file": None if n == 5 else "{0:04d}.png".format(n), "how": "size"}
                             for n in range(1, PAGES + 1)]}, f)
    held = Tiny(library, comic)
    with zipfile.ZipFile(str(held.single), "w", zipfile.ZIP_STORED) as zf:
        for name in sorted(os.listdir(str(comic))):
            zf.write(str(comic / name), name)
    held.first = held.pack()
    return held


def test_packing_writes_one_archive_per_chapter(tiny):
    made = tiny.made()
    assert len(made) == 3, made
    #named for sorting, with the label kept, and a label with characters a filesystem hates tidied
    assert made == [FIRST, SECOND, THIRD], made
    with zipfile.ZipFile(str(tiny.out / SECOND)) as zf:
        held = [n for n in zf.namelist() if n != "ComicInfo.xml"]
        info = ET.fromstring(zf.read("ComicInfo.xml"))
    #the missing flash page is simply absent, the rest are there
    assert held == ["0006.png", "0007.png", "0008.png", "0009.png"], held
    #ComicInfo says which chapter of how many, and keeps the label as the title
    assert (info.findtext("Series"), info.findtext("Number"), info.findtext("Count"),
            info.findtext("PageCount")) == ("Tiny", "2", "3", "4"), ET.tostring(info)[:200]
    assert info.findtext("Title") == "Arc 2 - Trouble: Part 1/2", info.findtext("Title")
    assert "exactly one chapter archive" in tiny.first.stdout, tiny.first.stdout[-300:]
    assert tiny.single.exists(), "the single archive went before anything asked it to"


def test_packing_again_writes_nothing(tiny):
    before = tiny.stamps()
    done = tiny.pack()
    assert "0 to write, 3 already" in done.stdout, done.stdout[:200]
    assert tiny.stamps() == before, "an archive was rewritten"


def test_a_page_replaced_with_a_better_copy_rewrites_only_its_chapter(tiny):
    (tiny.comic / "0011.png").write_bytes(b"z" * 9999)
    done = tiny.pack()
    assert "1 to write, 2 already" in done.stdout, done.stdout[:200]
    with zipfile.ZipFile(str(tiny.out / THIRD)) as zf:
        assert zf.getinfo("0011.png").file_size == 9999


def add_a_new_page(tiny):
    #a page scraped since the chapters were worked out
    (tiny.comic / "0013.png").write_bytes(b"n" * 1300)
    return tiny.pack()


def test_pages_scraped_since_join_the_last_chapter(tiny):
    done = add_a_new_page(tiny)
    with zipfile.ZipFile(str(tiny.out / THIRD)) as zf:
        assert "0013.png" in zf.namelist(), zf.namelist()
    assert "join chapter 3" in done.stdout, done.stdout[:300]


def test_a_damaged_chapter_archive_is_written_again(tiny):
    with zipfile.ZipFile(str(tiny.out / FIRST), "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("0001.png", b"wrong")
    done = tiny.pack()
    #rewritten rather than trusted
    assert "1 to write, 2 already" in done.stdout, done.stdout[:200]
    with zipfile.ZipFile(str(tiny.out / FIRST)) as zf:
        assert zf.getinfo("0001.png").file_size == 100, zf.namelist()
    assert tiny.single.exists()


def test_the_check_before_the_single_archive_is_given_up(tiny, chapters):
    add_a_new_page(tiny)
    pages = [{"n": n, "file": None if n == 5 else "{0:04d}.png".format(n)} for n in range(1, 14)]
    parcels = chapters.chapter_contents(str(tiny.comic), CHAPTERS, pages)
    assert chapters.verify_chapters(str(tiny.comic), str(tiny.out), parcels) is True, "a shelf that is right"
    kept = (tiny.out / THIRD).read_bytes()
    with zipfile.ZipFile(str(tiny.out / THIRD), "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("0010.png", b"x" * 5)
    assert chapters.verify_chapters(str(tiny.comic), str(tiny.out), parcels) is False, \
        "a chapter holding the wrong thing passed"
    (tiny.out / THIRD).write_bytes(kept)
    assert chapters.verify_chapters(str(tiny.comic), str(tiny.out), parcels) is True, "put back, it still fails"


def test_replacing_gives_up_the_single_archive_once_everything_checks_out(tiny, chapters):
    done = tiny.pack("--replace")
    assert done.returncode == 0, done.stdout[-300:]
    assert not tiny.single.exists()
    assert "Removed" in done.stdout, done.stdout[-200:]
    meta = read_meta(tiny.comic)
    #the comic still keeps archives, they are just per chapter
    assert meta["settings"]["cbz"] is True, meta["settings"]
    #and having chapters is what stops a scrape building a single one
    assert meta["chapters"].get("list"), meta["chapters"]
    assert meta["chapters"]["folder"] == "CBZs/Group/Tiny", meta["chapters"]
    assert meta["chapters"].get("packed"), meta["chapters"]
    #every page is still held somewhere
    inside = set()
    for name in tiny.made():
        with zipfile.ZipFile(str(tiny.out / name)) as zf:
            inside |= {n for n in zf.namelist() if n != "ComicInfo.xml"}
    pages = set(chapters.folder_pages(str(tiny.comic)))
    assert inside == pages, sorted(pages - inside)


def test_what_the_single_archive_holds_besides_the_pages_is_kept(tiny):
    #another scraper packed a copy of itself in with the pages, and the folder never had it
    with zipfile.ZipFile(str(tiny.single), "a") as zf:
        zf.writestr("Tiny/mirror_tiny.py", "print('the script that made this')")
    done = tiny.pack("--replace")
    assert done.returncode == 0, done.stdout[-400:]
    assert not tiny.single.exists()
    kept = tiny.out / "mirror_tiny.py"
    assert kept.read_text() == "print('the script that made this')", "kept beside the chapter archives"
    assert not [name for name in tiny.made() if name.endswith(".writing")]


def test_a_single_archive_whose_extra_would_overwrite_a_file_is_kept(tiny):
    with zipfile.ZipFile(str(tiny.single), "a") as zf:
        zf.writestr("mirror_tiny.py", "the archive's copy")
    (tiny.out / "mirror_tiny.py").write_text("one already on the shelf")
    done = tiny.pack("--replace")
    assert done.returncode != 0
    assert tiny.single.exists(), "kept, since what it holds could not be kept another way"
    assert (tiny.out / "mirror_tiny.py").read_text() == "one already on the shelf", "and nothing overwritten"


def test_a_comic_with_no_archive_named_keeps_its_chapters_on_the_shelf(tmp_path, chapters):
    #adopted or uploaded, with no cbz_path: its chapters go where a scrape would have filed its one
    #archive, in the CBZs tree beside Uncompressed - not in a folder beside its loose pages
    root = tmp_path / "lib"
    comic = root / "Uncompressed" / "Group" / "Adopted"
    comic.mkdir(parents=True)
    (root / "CBZs").mkdir()
    shelf = chapters.chapter_folder(str(comic), {"settings": {}}, str(root))
    assert shelf == str(root / "CBZs" / "Group" / "Adopted")
    #a library not laid out that way still keeps them beside the pages, as before
    loose = tmp_path / "loose" / "Adopted"
    loose.mkdir(parents=True)
    assert chapters.chapter_folder(str(loose), {"settings": {}}) == str(loose) + "_chapters"
