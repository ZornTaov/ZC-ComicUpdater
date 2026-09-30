#an update of a comic kept in chapters: the new pages go into the index, the alignment is worked out again,
#and the last chapter's archive is repacked to hold them - unless the library has turned that off.
import json
import os
import zipfile

import pytest

from conftest import Site, PNG, pages_in, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]

HELD = 12


def image(n):
    #every page a different size, so the alignment has something to go on
    return PNG + bytes([n]) * n


class Serial(Site):
    pages = 14
    #a page whose image will not download, which ends a run with the pages before it saved
    broken = 0

    def do_GET(self):
        bit = self.path.rsplit("/", 1)[-1].split(".")[0]
        if not bit.isdigit():
            self.send_error(404)
            return
        n = int(bit)
        if self.path.startswith("/img/") and n == self.broken:
            self.send_error(500)
            return
        if self.path.startswith("/img/"):
            self.send(image(n), "image/png")
            return
        link = '<a href="/p/{0}">Next</a>'.format(n + 1) if n < self.pages else ""
        self.send('<html><head><title>Page {0}</title></head><body><div id="wrap">{1}'
                  '<img id="cc-comic" src="/img/{0:04d}.png"></div></body></html>'.format(n, link))


class Held:
    def __init__(self, site, library, config, comic, index, handler):
        self.site, self.library, self.config = site, library, config
        self.comic, self.index, self.handler = comic, index, handler
        self.shelf = library / "CBZs"
        self.out = self.shelf / "MyComic"

    def update(self):
        return run("update_comics.py", self.library, "--progress", "0", "--config", self.config, timeout=600)

    def chapter(self, number):
        #the pages the archive for one chapter holds
        name = [f for f in os.listdir(str(self.out)) if "c{0:03d}".format(number) in f][0]
        with zipfile.ZipFile(str(self.out / name)) as zf:
            return [n for n in zf.namelist() if n.endswith(".png")]

    def chapter_file(self, number):
        return self.out / [f for f in os.listdir(str(self.out)) if "c{0:03d}".format(number) in f][0]


@pytest.fixture
def held(serve, library, config, chapters):
    #the comic as it stands: 12 pages held, in three chapters, already packed
    handler = type("Site", (Serial,), {})
    site = serve(handler)
    comic = library / "Uncompressed" / "MyComic"
    comic.mkdir()
    for n in range(1, HELD + 1):
        (comic / "{0:04d}.png".format(n)).write_bytes(image(n))
    index = chapters.index_path(str(comic))
    with open(index, "w", encoding="utf-8") as f:
        for n in range(1, HELD + 1):
            f.write(json.dumps({"n": n, "url": "{0}/p/{1}".format(site, n),
                                "src": "{0}/img/{1:04d}.png".format(site, n),
                                "file": "{0:04d}.png".format(n), "title": "Page {0}".format(n),
                                "bytes": len(PNG) + n}) + "\n")
    write_meta(comic, {
        "schema": 2,
        "settings": {"url": "{0}/p/{1}".format(site, HELD), "output": "Uncompressed/MyComic",
                     "cbz_path": "CBZs/MyComic.cbz", "cbz": True, "increment": HELD,
                     "direction_check": False},
        "history": {"runs": [], "index_cache": os.path.basename(index)},
        "chapters": {"source": "urls", "folder": "CBZs/MyComic",
                     "list": [{"number": 1, "label": "One", "start_page": 1, "end_page": 4, "pages": 4,
                               "start_file": "0001.png"},
                              {"number": 2, "label": "Two", "start_page": 5, "end_page": 8, "pages": 4,
                               "start_file": "0005.png"},
                              {"number": 3, "label": "Three", "start_page": 9, "end_page": 12, "pages": 4,
                               "start_file": "0009.png"}]}})
    for step in ("align", "pack"):
        done = run("chapters.py", step, comic, "--root", library, timeout=180)
        assert done.returncode == 0, "{0} failed in setting up:\n{1}".format(step, done.stdout[-400:])
    assert len(os.listdir(str(library / "CBZs" / "MyComic"))) == 3
    return Held(site, library, config, comic, index, handler)


def test_an_update_finds_new_pages_and_keeps_the_chapters_in_step(held, chapters):
    done = held.update()
    files = pages_in(held.comic)
    assert len(files) == 14, "the two new pages were saved: {0}".format(files[-3:])

    lines = chapters.read_index(held.index)
    assert [line["n"] for line in lines] == list(range(1, 15)), "the index grew with them, in order"
    last = lines[-1]
    assert last["url"].endswith("/p/14") and last["file"] == "0014.png" \
        and last["bytes"] == os.path.getsize(str(held.comic / "0014.png")), \
        "with the address, the filename and the real size: {0}".format(last)
    assert last["title"] == "Page 14", last

    with open(held.index.replace(".jsonl", ".align.json"), encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["settled"] and len(saved["pages"]) == 14, "the alignment was worked out again and settled"

    held_now = held.chapter(3)
    assert "0013.png" in held_now and "0014.png" in held_now, "the last chapter archive holds the new pages"
    newest = os.path.getmtime(str(held.chapter_file(3)))
    for name in os.listdir(str(held.out)):
        if "c003" not in name:
            assert os.path.getmtime(str(held.out / name)) < newest, "an earlier chapter was rewritten: " + name
    assert not (held.shelf / "MyComic.cbz").exists(), "a single archive came back: {0}".format(
        sorted(os.listdir(str(held.shelf))))
    assert "chapters:" in done.stdout, "the run should say what it did:\n" + done.stdout[-400:]


def test_a_second_update_with_nothing_new_writes_nothing(held):
    held.update()
    again = held.update()
    assert "chapters:" not in again.stdout, \
        [line for line in again.stdout.splitlines() if "chapters" in line]
    assert "up to date" in again.stdout, again.stdout[-300:]


def test_pages_saved_before_a_run_fails_are_still_packed(held, chapters):
    #the site's newest page will not download, so the run fails - after saving the page before it
    held.handler.broken = 14
    done = held.update()
    assert "FAILED exit 4" in done.stdout and "+1 page" in done.stdout, done.stdout[-600:]
    assert "0013.png" in held.chapter(3), "the page it did save should be packed: " + done.stdout[-600:]
    #and the same again tomorrow gains nothing, so packs nothing
    again = held.update()
    assert "chapters:" not in again.stdout, again.stdout[-400:]


def test_an_index_line_cut_off_by_a_kill_is_read_past_not_failed_on(held, chapters):
    #the updater lines a comic up straight after a run it killed, before any scrape has mended the index
    with open(held.index, "rb") as f:
        whole = f.read()
    with open(held.index, "ab") as f:
        f.write(b'{"n": 13, "url": "http://127.0.0.1/p/13", "src": "htt')
    assert [line["n"] for line in chapters.read_index(held.index)] == list(range(1, HELD + 1))
    done = run("chapters.py", "align", held.comic, "--root", held.library, timeout=180)
    assert done.returncode == 0, done.stdout[-400:]
    #reading it changes nothing: taking the line off is the next scrape's, which records the page again
    with open(held.index, "rb") as f:
        assert f.read() != whole
    #a line that will not read in the middle of the file is something else, and is not passed over
    with open(held.index, "wb") as f:
        f.write(whole.replace(b'"n": 5,', b'"n": 5', 1))
    with pytest.raises(ValueError):
        chapters.read_index(held.index)


def test_with_pack_chapters_off_an_update_leaves_the_archives_until_packed_by_hand(held, chapters):
    (held.config / "ComicScraper.json").write_text(json.dumps({"pack_chapters": False}))
    #the site serves four more pages than are held now
    held.handler.pages = 16
    done = held.update()
    assert len(pages_in(held.comic)) == 16, "the new pages were still scraped"
    assert "chapters:" not in done.stdout, [line for line in done.stdout.splitlines() if "chapters" in line]
    assert "0015.png" not in held.chapter(3), "the archives should not hold them yet"
    assert [line["n"] for line in chapters.read_index(held.index)] == list(range(1, 17)), \
        "the index keeps up anyway, so nothing has to be walked again"

    #packing by hand then brings them in
    run("chapters.py", "pack", held.comic, "--root", held.library, timeout=180)
    now = held.chapter(3)
    assert "0015.png" in now and "0016.png" in now, now[-4:]
