#a record of which page is which that begins in the middle: position is meaning, so line 1 has to be the
#comic's page 1. such a record cannot be carried on from, and nothing should write one. a real browser walks
#a five page comic served from here.
import json

import pytest

from conftest import PNG_240, Comic, run, write_index, write_meta

PAGES = 5
CACHE = "MyComic.stub.jsonl"
pytestmark = [pytest.mark.browser, pytest.mark.slow]


@pytest.fixture
def site(serve):
    return serve(Comic)


@pytest.fixture
def comic(library, site):
    folder = library / "Uncompressed" / "MyComic"
    folder.mkdir()
    for n in range(1, PAGES + 1):
        (folder / "{0:04d}.png".format(n)).write_bytes(PNG_240)
    return folder


def write_metadata(folder, site, index_cache=None):
    history = {"first_page_url": site + "/p/1", "first_page_number": 1, "runs": []}
    if index_cache:
        history["index_cache"] = index_cache
    write_meta(folder, {"schema": 2, "settings": {"url": site + "/p/{0}".format(PAGES), "output": str(folder),
                                                  "cbz_path": None, "increment": PAGES, "prefix": False,
                                                  "javascript": False, "cbz": False, "ended": False},
                        "state": {}, "history": history})


def read_index(path):
    with open(str(path), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_a_scrape_part_way_through_a_comic_does_not_start_a_record(config, comic, site):
    write_metadata(comic, site)
    done = run("mirror_base.py", "-o", comic, "--no-cbz", "--keep-index", "-i", "4", "--prime",
               site + "/p/4", timeout=600)
    made = [p.name for p in (config / "index").iterdir()]
    assert "has to begin at the comic's first page" in done.stdout, done.stdout[-300:]
    assert not made, made


def test_a_scrape_from_the_first_page_still_keeps_one(config, comic, site):
    write_metadata(comic, site)
    run("mirror_base.py", "-o", comic, "--no-cbz", "--keep-index", "-i", "1", "--prime", site + "/p/1",
        timeout=600)
    made = [p for p in (config / "index").iterdir() if p.name.endswith(".jsonl")]
    assert len(made) == 1, made
    lines = read_index(made[0])
    assert len(lines) == 1 and lines[0]["n"] == 1, "should hold the page it started on: {0}".format(lines)


def test_a_record_that_begins_in_the_middle_is_thrown_away_on_restart(config, library, comic, site):
    write_metadata(comic, site, CACHE)
    #exactly what a scrape of an up to date comic leaves: the newest page, called page one
    write_index(config / "index" / CACHE, [{"n": 1, "url": site + "/p/{0}".format(PAGES),
                                            "src": site + "/img/0005.png", "file": "0005.png",
                                            "title": "Comic 5", "bytes": len(PNG_240)}])
    done = run("chapters.py", "index", comic, "--root", library, "--restart", "--start", site + "/p/1",
               timeout=600)
    assert "Throwing away the record of 1 page(s)" in done.stdout, done.stdout[:500]
    lines = read_index(config / "index" / CACHE)
    assert len(lines) == PAGES, "the whole comic should be walked: {0}".format([one.get("url") for one in lines])
    assert lines[0]["url"].endswith("/p/1"), lines[:1]
    assert lines[-1]["url"].endswith("/p/{0}".format(PAGES)), lines[-1:]
    assert [one["n"] for one in lines] == list(range(1, PAGES + 1)), [one["n"] for one in lines]


def test_without_restart_a_record_carries_on_as_before(config, library, comic, site):
    write_metadata(comic, site, CACHE)
    write_index(config / "index" / CACHE, [
        {"n": n, "url": site + "/p/{0}".format(n), "src": site + "/img/{0:04d}.png".format(n),
         "file": "{0:04d}.png".format(n), "title": "Comic {0}".format(n)} for n in (1, 2)])
    done = run("chapters.py", "index", comic, "--root", library, timeout=600)
    lines = read_index(config / "index" / CACHE)
    assert "Throwing away" not in done.stdout, done.stdout[:300]
    assert len(lines) == PAGES, "the walk should carry on to the end: {0}".format([one.get("n") for one in lines])
