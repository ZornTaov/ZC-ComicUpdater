#a comic scraped long ago into one archive, given a chapter list from the editor afterwards: the list is
#saved, the comic walked once to learn which page is which, split into one archive per chapter, and the
#list's address cleared again without losing the chapters. a walk long enough to matter says how far it
#has got while it runs, and stopping it stops it.
import zipfile

import pytest

from conftest import PNG, Comic, Site, read_meta, wait_until, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]
TOTAL = 9
#named chapters, not numbered ones, the way some comic themes list them
CHAPTERS = [("Chapter One", 1), ("Chapter Two", 4), ("Chapter Three", 7)]
NAME = "Uncompressed/Group/MyComic"


class Archived(Site):
    #a comic at /comic/pageNNN/ whose archive page heads each chapter with its title. every image is a
    #different size, so each page can be told apart from its neighbours by size alone
    def do_GET(self):
        if self.path == "/archive":
            starts = dict((at, label) for label, at in CHAPTERS)
            rows = ["<h1>The Archive</h1>"]
            for n in range(1, TOTAL + 1):
                if n in starts:
                    rows.append('<h3 class="comic-archive-chapter">{0}</h3>'.format(starts[n]))
                rows.append('<span class="comic-archive-date">Jan 0{0}, 2005</span>'.format(n))
                rows.append('<a href="/comic/page{0:03d}/">page {0}</a>'.format(n))
            self.send("<html><body>" + "".join(rows) + "</body></html>")
            return
        bit = "".join(c for c in self.path.rsplit("/", 1)[-1].split(".")[0] if c.isdigit())
        if not bit:
            bit = "".join(c for c in self.path.strip("/").rsplit("/", 1)[-1] if c.isdigit())
        if not bit:
            self.send_error(404)
            return
        n = int(bit)
        if self.path.startswith("/img/"):
            self.send(PNG + bytes([n]) * n, "image/png")
            return
        link = '<a href="/comic/page{0:03d}/">Next</a>'.format(n + 1) if n < TOTAL else ""
        self.send('<html><head><title>Page {0}</title></head><body><div id="wrap">{1}'
                  '<img id="cc-comic" src="/img/page{0:03d}.png"></div></body></html>'.format(n, link))


def test_a_chapter_list_added_from_the_editor_splits_an_old_comic(serve, library, web):
    site = serve(Archived)
    comic = library / "Uncompressed" / "Group" / "MyComic"
    shelf = library / "CBZs" / "Group"
    comic.mkdir(parents=True)
    shelf.mkdir(parents=True)
    #a comic as it would be today: scraped long ago, one archive, nothing recorded about which page is which
    for n in range(1, TOTAL + 1):
        (comic / "{0:04d}_page{1:03d}.png".format(n, n)).write_bytes(PNG + bytes([n]) * n)
    write_meta(comic, {"schema": 2,
                       "settings": {"url": "{0}/comic/page{1:03d}/".format(site, TOTAL), "output": NAME,
                                    "cbz_path": "CBZs/Group/MyComic.cbz", "cbz": True, "prefix": True,
                                    "increment": TOTAL, "direction_check": False},
                       "history": {"first_page_url": site + "/comic/page001/", "first_page_number": 1,
                                   "runs": []}})
    single = shelf / "MyComic.cbz"
    with zipfile.ZipFile(single, "w", zipfile.ZIP_STORED) as zf:
        for page_file in sorted(comic.iterdir()):
            zf.write(page_file, page_file.name)
    page = web()

    #the editor shows there is nothing chaptered yet, and no index, so it would have to walk
    code, detail = page.call("/api/comic?name=" + NAME)
    assert code == 200, detail
    assert not detail["chapters"]["source_url"], detail["chapters"]
    assert detail["indexed"] is False, detail

    #saving a chapter list through the editor
    code, answer = page.call("/api/settings", {"name": NAME, "updated": detail["updated"],
                                               "settings": {"chapters_url": site + "/archive"}})
    assert code == 200 and answer.get("saved"), answer
    assert "chapters" in (answer.get("changed") or {}), answer
    assert (read_meta(comic).get("chapters") or {}).get("source_url") == site + "/archive"
    assert page.call("/api/settings", {"name": NAME, "settings": {"chapters_url": "the archive page"}})[0] == 400, \
        "a chapter list that is not an address should be refused"

    #working the chapters out, which means walking the comic first
    code, answer = page.call("/api/chapterize", {"name": NAME})
    assert code == 200 and answer.get("walking") is True, answer
    assert page.wait_idle(900), "the chapters were never worked out"
    meta = read_meta(comic)
    block = meta.get("chapters") or {}
    assert [c["label"] for c in block.get("list", [])] == [label for label, _ in CHAPTERS], block
    assert [c["start_page"] for c in block["list"]] == [at for _, at in CHAPTERS], block["list"]
    assert meta["history"].get("index_cache"), "an index should have been built on the way"
    folder = shelf / "MyComic"
    made = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    assert made == ["MyComic - c{0:03d} - {1}.cbz".format(at, label)
                    for at, (label, _) in enumerate(CHAPTERS, 1)], made
    inside = set()
    for name in made:
        with zipfile.ZipFile(folder / name) as zf:
            inside |= {n for n in zf.namelist() if n.endswith(".png")}
    assert len(inside) == TOTAL, sorted(inside)
    assert not single.exists(), "the single archive should be given up: {0}".format(
        sorted(p.name for p in shelf.iterdir()))
    assert meta["settings"]["cbz"] is True, "the comic should still keep archives"

    #asking again needs no second walk
    _, detail = page.call("/api/comic?name=" + NAME)
    assert detail["indexed"] is True, detail
    assert detail["chapters"]["count"] == len(CHAPTERS), detail["chapters"]
    _, answer = page.call("/api/chapterize", {"name": NAME})
    assert answer.get("walking") is False, answer
    assert page.wait_idle(900), "the second chaptering never finished"
    assert len(read_meta(comic)["chapters"]["list"]) == len(CHAPTERS)

    #clearing the chapter list's address again keeps the chapters it found
    _, detail = page.call("/api/comic?name=" + NAME)
    code, answer = page.call("/api/settings", {"name": NAME, "updated": detail["updated"],
                                               "settings": {"chapters_url": ""}})
    assert code == 200 and answer.get("saved"), answer
    block = read_meta(comic)["chapters"]
    assert block.get("source_url") is None and len(block["list"]) == len(CHAPTERS), block


class Endless(Comic):
    #far more pages than any test waits for, so the walk is always still going when it is looked at
    pages = 100000


def test_a_long_walk_says_how_far_it_has_got_and_can_be_stopped(serve, library, web):
    site = serve(Endless)
    comic = library / "Uncompressed" / "Long"
    (comic / "0001.png").parent.mkdir(parents=True)
    (comic / "0001.png").write_bytes(PNG)
    write_meta(comic, {"schema": 2,
                       "settings": {"url": site + "/p/1", "output": "Uncompressed/Long", "cbz": True},
                       "history": {"first_page_url": site + "/p/1", "first_page_number": 1, "runs": []}})
    page = web()
    code, answer = page.call("/api/chapterize", {"name": "Uncompressed/Long", "every": "100"})
    assert code == 200 and answer.get("walking") is True, answer

    #held back until the step ended, a walk of thousands of pages showed nothing at all for most of an hour
    def doing():
        current = page.call("/api/state")[1]["current"] or {}
        return "indexed" in (current.get("doing") or "") and current["doing"]
    said = wait_until(doing, limit=120, why="the running job never said how far the walk had got")
    assert said.startswith("index: indexed "), said
    assert "indexed 25 pages" in page.said(), "the walk's progress should reach the log as it happens"

    assert page.call("/api/stop", {})[1].get("stopping") is True
    state = page.wait_idle(60)
    assert state is not None, "stopping the job did not stop the walk"
    last = state["history"][0]
    assert last["doing"] is None, last
    assert "carries on from where it got to" in page.said(), page.said()[-400:]
    #stopped in the walk, so nothing after it ran
    assert not (read_meta(comic).get("chapters") or {}).get("list"), "no chapters should have been saved"
