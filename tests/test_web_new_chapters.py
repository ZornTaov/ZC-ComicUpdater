#a comic added from the web page with a chapter list: the scrape keeps an index as it goes, so the chapters
#are worked out and archived one per chapter with no separate walk. a comic added without one is left as a
#single archive, with no index started for it.
import os
import zipfile

import pytest

from conftest import PNG, Site, pages_in, read_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]
TOTAL = 10
CHAPTERS = [("Beginnings", 1), ("The Middle Bit", 5), ("Where It Ends", 8)]


class Chaptered(Site):
    #every image a different size, so each page is its own
    def do_GET(self):
        if self.path == "/archive":
            starts = dict((at, label) for label, at in CHAPTERS)
            rows = []
            for n in range(1, TOTAL + 1):
                if n in starts:
                    rows.append('<h2 class="chapter">{0}</h2>'.format(starts[n]))
                rows.append('<a href="/p/{0}">page {0}</a>'.format(n))
            self.send("<html><body>" + "".join(rows) + "</body></html>")
            return
        bit = self.path.rsplit("/", 1)[-1].split(".")[0]
        if not bit.isdigit():
            self.send_error(404)
            return
        n = int(bit)
        if self.path.startswith("/img/"):
            self.send(PNG + bytes([n]) * n, "image/png")
            return
        link = '<a href="/p/{0}">Next</a>'.format(n + 1) if n < TOTAL else ""
        self.send('<html><head><title>Page {0}</title></head><body><div id="wrap">{1}'
                  '<img id="cc-comic" src="/img/{0:04d}.png"></div></body></html>'.format(n, link))


@pytest.fixture
def site(serve):
    return serve(Chaptered)


def test_a_comic_added_with_a_chapter_list_is_archived_by_chapter(site, library, config, web, chapters):
    page = web()
    code, answer = page.call("/api/add", {"rows": [{"folder": "Chaptered", "url": site + "/p/1",
                                                    "chapters": site + "/archive"}]})
    assert code == 200, answer
    assert page.call("/api/add", {"rows": [{"folder": "Nope", "url": site + "/p/1",
                                            "chapters": "the archive page"}]})[0] == 400, \
        "a chapter list that is not an address should be refused"
    assert page.wait_idle(600), "the add never finished"

    comic = library / "Uncompressed" / "Chaptered"
    files = pages_in(comic)
    assert len(files) == TOTAL, files
    meta = read_meta(comic)
    assert meta["history"].get("index_cache"), "it should keep an index while scraping: {0}".format(
        list(meta["history"].keys()))
    lines = chapters.read_index(str(config / "index" / meta["history"]["index_cache"]))
    #every page in it, so no walk was needed, each with its file and its real size
    assert len(lines) == TOTAL, len(lines)
    assert all(line["file"] and line["bytes"] == os.path.getsize(str(comic / files[line["n"] - 1]))
               for line in lines), lines[:2]

    block = meta.get("chapters", {})
    assert len(block.get("list", [])) == len(CHAPTERS), block
    assert [c["label"] for c in block["list"]] == [label for label, _ in CHAPTERS], block["list"]
    #and the archive page is remembered for next time
    assert block["source_url"] == site + "/archive", block

    out = library / "CBZs" / "Chaptered"
    made = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
    assert len(made) == len(CHAPTERS), made
    assert made[1] == "Chaptered - c002 - The Middle Bit.cbz", made
    with zipfile.ZipFile(out / made[0]) as zf:
        held = sorted(n for n in zf.namelist() if n.endswith(".png"))
    assert len(held) == CHAPTERS[1][1] - CHAPTERS[0][1], held
    assert not (library / "CBZs" / "Chaptered.cbz").exists(), sorted(p.name for p in (library / "CBZs").iterdir())
    assert any("chapters" in line for line in page.log), page.log[-6:]


def test_a_comic_added_without_a_chapter_list_is_left_as_one_archive(site, library, web):
    page = web()
    page.call("/api/add", {"rows": [{"folder": "Plain", "url": site + "/p/1"}]})
    assert page.wait_idle(600), "the add never finished"
    assert (library / "Uncompressed" / "Plain").is_dir()
    assert (library / "CBZs" / "Plain" / "Plain.cbz").is_file(), sorted(p.name for p in (library / "CBZs").iterdir())
    plain = read_meta(library / "Uncompressed" / "Plain")
    assert "chapters" not in plain and not plain["history"].get("index_cache"), \
        (plain.get("chapters"), plain["history"].get("index_cache"))
