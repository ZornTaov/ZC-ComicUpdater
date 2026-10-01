#a comic added from the web page to be cut every so many pages: the scrape keeps its index as it goes and
#the parts are written from it, with no walk and no single archive - whether it is scraped whole straight
#away or primed and finished by an update. and a comic primed first and set to be cut afterwards does not
#keep the one-page archive its prime built.
import os

import pytest

from conftest import pages_in, read_meta, run, write_meta
from test_web_new_chapters import TOTAL, Chaptered

pytestmark = [pytest.mark.browser, pytest.mark.slow]
PARTS = ["Pages 1-4", "Pages 5-8", "Pages 9-12"]


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
    assert "Walking" not in page.said(), page.log[-8:]


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
