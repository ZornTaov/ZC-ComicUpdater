#a comic added from the web page to be cut every so many pages: the scrape keeps its index as it goes and
#the parts are written from it, with no walk and no single archive - whether it is scraped whole straight
#away or primed and finished by an update. and a comic primed first and set to be cut afterwards does not
#keep the one-page archive its prime built. a first scrape that fails on its last page is cut all the same,
#and a comic set to be cut once it had caught up is cut by an update that finds nothing new.
import os

import pytest

from comiclib import runlogs
from conftest import pages_in, read_meta, run, write_meta
from test_web_new_chapters import TOTAL, Chaptered

pytestmark = [pytest.mark.browser, pytest.mark.slow]
PARTS = ["Pages 1-4", "Pages 5-8", "Pages 9-12"]


class EndsBroken(Chaptered):
    #the newest page links on to one whose picture is not up yet: the scrape saves every page before it and
    #then fails to download, as a site putting up its next page before the image does
    def do_GET(self):
        if self.path == "/p/{0}".format(TOTAL):
            self.send('<html><body><div id="wrap"><a href="/p/{0}">Next</a><img id="cc-comic" '
                      'src="/img/{1:04d}.png"></div></body></html>'.format(TOTAL + 1, TOTAL))
        elif self.path == "/p/{0}".format(TOTAL + 1):
            self.send('<html><body><div id="wrap"><img id="cc-comic" src="/missing/{0:04d}.png">'
                      '</div></body></html>'.format(TOTAL + 1))
        elif self.path.startswith("/missing/"):
            self.send_error(404)
        else:
            super().do_GET()


@pytest.fixture
def site(serve):
    return serve(Chaptered)


def shelf_of(library, name):
    folder = library / "CBZs" / name
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def assert_cut(library, config, chapters, name):
    comic = library / "Uncompressed" / name
    assert len(pages_in(comic)) == TOTAL, pages_in(comic)
    meta = read_meta(comic)
    block = meta.get("chapters") or {}
    assert block.get("source") == "every" and block.get("every") == 4, block
    assert [c["label"] for c in block.get("list", [])] == PARTS, block.get("list")
    #every page in the index the scrape kept, so nothing had to walk the comic
    lines = chapters.read_index(str(config / "index" / meta["history"]["index_cache"]))
    assert len(lines) == TOTAL, len(lines)
    made = shelf_of(library, name)
    assert made == ["{0} - c00{1} - {2}.cbz".format(name, at, part) for at, part in enumerate(PARTS, 1)], \
        "the parts, and no single archive of the lot: {0}".format(made)


def test_a_comic_added_to_be_cut_is_archived_in_parts_without_a_walk(site, library, config, web, chapters):
    page = web()
    assert page.call("/api/add", {"rows": [{"folder": "Nope", "url": site + "/p/1"}], "every": "four"})[0] \
        == 400, "pages per part that is not a number should be refused"
    code, answer = page.call("/api/add", {"rows": [{"folder": "Cut", "url": site + "/p/1"}], "every": "4"})
    assert code == 200, answer
    assert page.wait_idle(600), "the add never finished"
    assert_cut(library, config, chapters, "Cut")
    said = page.said()
    assert "Walking" not in said, page.log[-8:]
    #each step after the scrape said as it starts and how long it took, as an update's are, not left silent
    for step in ("chapters: writing the chapter archives ...", "chapters: pack took"):
        assert step in said, page.log[-12:]
    #and in the comic's own log, after its scrape
    (log,) = [os.path.join(where, name) for where, _, names in os.walk(runlogs.logs_folder()) for name in names]
    with open(log, encoding="utf-8") as f:
        kept = f.read()
    assert "--- chapters: pack:" in kept, kept[-400:]
    assert "chapters worked out in" in kept.splitlines()[-1], kept[-400:]


def test_a_first_scrape_that_fails_on_its_last_page_is_cut_all_the_same(serve, library, config, web, chapters):
    #the add packed only a scrape that ended well, and the updates after found nothing new, so a whole
    #comic sat unpacked until its chapters were worked out by hand
    broken = serve(EndsBroken)
    page = web()
    code, answer = page.call("/api/add", {"rows": [{"folder": "Cut", "url": broken + "/p/1"}], "every": "4"})
    assert code == 200, answer
    assert page.wait_idle(600), "the add never finished"
    said = page.said()
    assert "download failed" in said.lower(), "the scrape was meant to fail on its last page: {0}".format(
        page.log[-12:])
    assert "chapters: pack took" in said, page.log[-12:]
    assert_cut(library, config, chapters, "Cut")


def test_a_caught_up_comic_set_to_be_cut_is_cut_by_an_update_with_nothing_new(site, library, config, web,
                                                                             chapters):
    page = web()
    page.call("/api/add", {"rows": [{"folder": "Later", "url": site + "/p/1"}]})
    assert page.wait_idle(600), "the add never finished"
    assert shelf_of(library, "Later") == ["Later.cbz"], shelf_of(library, "Later")
    comic = library / "Uncompressed" / "Later"
    meta = read_meta(comic)
    meta["chapters"] = {"source": "every", "every": 4, "list": []}
    write_meta(comic, meta)

    done = run("update_comics.py", library, "--progress", "0", timeout=600)
    assert done.returncode == 0, done.stdout[-600:]
    assert "No new pages" in done.stdout or "up to date" in done.stdout, done.stdout[-600:]
    assert_cut(library, config, chapters, "Later")
    assert (read_meta(comic).get("chapters") or {}).get("packed")
    #and once packed, an update with nothing new leaves it be
    again = run("update_comics.py", library, "--progress", "0", timeout=600)
    assert "writing the chapter archives" not in again.stdout, again.stdout[-600:]


def test_a_comic_primed_to_be_cut_is_cut_by_the_update_that_finishes_it(site, library, config, web, chapters):
    page = web()
    code, answer = page.call("/api/add", {"rows": [{"folder": "Cut", "url": site + "/p/1"}],
                                          "every": 4, "prime": True})
    assert code == 200, answer
    assert page.wait_idle(300), "the prime never finished"
    comic = library / "Uncompressed" / "Cut"
    assert pages_in(comic) == ["0001.png"], pages_in(comic)
    assert (read_meta(comic).get("chapters") or {}).get("every") == 4, "remembered before the prime ran"
    assert shelf_of(library, "Cut") == [], "a comic in parts never builds the single archive"

    done = run("update_comics.py", library, "--progress", "0", timeout=600)
    assert done.returncode == 0, done.stdout[-600:]
    assert "Walking" not in done.stdout, done.stdout[-600:]
    assert_cut(library, config, chapters, "Cut")


def test_a_comic_primed_then_set_to_be_cut_gives_up_its_one_page_archive(site, library, config, web, chapters):
    page = web()
    page.call("/api/add", {"rows": [{"folder": "Later", "url": site + "/p/1"}], "prime": True})
    assert page.wait_idle(300), "the prime never finished"
    assert shelf_of(library, "Later") == ["Later.cbz"], shelf_of(library, "Later")
    #set to be cut afterwards, as the edit form does
    comic = library / "Uncompressed" / "Later"
    meta = read_meta(comic)
    meta["chapters"] = {"source": "every", "every": 4, "list": []}
    write_meta(comic, meta)

    done = run("update_comics.py", library, "--progress", "0", timeout=600)
    assert done.returncode == 0, done.stdout[-600:]
    assert_cut(library, config, chapters, "Later")
    assert not os.path.exists(str(library / "CBZs" / "Later" / "Later.cbz"))
