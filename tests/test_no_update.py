#a comic that is up to date gets looked at every day and gains nothing. a look is not an update: it must not
#add a run to the history saying a page was saved, nor rewrite the metadata (and with it the archive's copy)
#for no reason. but a comic that does gain a page, or comes good after a failed run, is news.
import json
import os
import time

import pytest

from conftest import Comic, pages_in, read_meta, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Growing(Comic):
    #three pages to begin with; a test puts a fourth up by raising `pages` on its own subclass
    pages = 3

    def image(self, name):
        #every page its own bytes, as a real comic's are
        return self.png + name.encode()


@pytest.fixture
def comic(serve, tmp_path):
    handler = type("Site", (Growing,), {})
    base = serve(handler)
    folder = tmp_path / "lib" / "Uncompressed" / "MyComic"
    folder.mkdir(parents=True)
    return handler, base, folder


def scrape(folder, url):
    done = run("mirror_base.py", "-o", folder, "--no-cbz", url)
    return done.returncode, done.stdout + done.stderr


def runs_of(folder):
    try:
        meta = read_meta(folder)
    except (OSError, ValueError):
        return None, []
    return meta, (meta.get("history") or {}).get("runs") or []


def summary(runs):
    return [(r.get("pages_saved"), r.get("exit_code"), r.get("stop_reason")) for r in runs]


def first_scrape(base, folder):
    #the first scrape, which really does fetch the comic
    code, out = scrape(folder, base + "/p/1")
    meta, runs = runs_of(folder)
    assert code == 0, out.strip().splitlines()[-3:]
    assert len(pages_in(folder)) == 3, sorted(os.listdir(folder))
    assert len(runs) == 1, summary(runs)
    return meta


def test_the_first_scrape_records_its_run(comic):
    _, base, folder = comic
    first_scrape(base, folder)


def test_a_run_with_nothing_new_writes_nothing_down(comic):
    _, base, folder = comic
    meta = first_scrape(base, folder)
    was_updated = meta.get("updated")
    was_mtime = os.path.getmtime(folder / "mirror_metadata.json")

    #a second later, so a rewrite would show in the file's time
    time.sleep(1.1)
    code, out = scrape(folder, meta["settings"]["url"])
    meta, runs = runs_of(folder)
    assert code == 0, out.strip().splitlines()[-3:]
    assert "No new pages" in out, [line for line in out.splitlines() if "new pages" in line]
    assert len(runs) == 1, "a second run was recorded: {0}".format(summary(runs))
    assert os.path.getmtime(folder / "mirror_metadata.json") == was_mtime and meta.get("updated") == was_updated, \
        "the metadata was rewritten: {0} vs {1}".format(meta.get("updated"), was_updated)

    #and again, twice more, as a daily run would: a history that stacks would already show it
    for _ in range(2):
        scrape(folder, meta["settings"]["url"])
    meta, runs = runs_of(folder)
    assert len(runs) == 1, "the history should still be one run, not several: {0}".format(summary(runs))
    #what the runs say they saved still matches what is held
    assert sum(r.get("pages_saved") or 0 for r in runs) == 3, summary(runs)


def test_a_page_the_comic_really_puts_up_is_recorded(comic):
    handler, base, folder = comic
    meta = first_scrape(base, folder)
    was_updated = meta.get("updated")
    handler.pages = 4
    scrape(folder, meta["settings"]["url"])
    meta, runs = runs_of(folder)
    assert len(pages_in(folder)) == 4, pages_in(folder)
    assert len(runs) == 2, summary(runs)
    assert meta.get("updated") != was_updated, meta.get("updated")


def test_a_clean_run_after_a_failed_one_is_recorded(comic):
    _, base, folder = comic
    meta = first_scrape(base, folder)
    #a failure written in by hand, as a run that could not find the image would leave behind
    meta["history"]["runs"].append({"run_id": "made-up", "started": "2020-01-01T00:00:00Z",
                                    "pages_saved": 0, "completed": False, "exit_code": 3,
                                    "stop_reason": "image element not found"})
    write_meta(folder, meta)
    before = len(meta["history"]["runs"])

    scrape(folder, meta["settings"]["url"])
    meta, runs = runs_of(folder)
    #the comic gained nothing, but that it reads as well again is news
    assert len(runs) == before + 1, summary(runs)
    assert runs[-1].get("exit_code") == 0, summary(runs[-2:])

    #and the one after that is quiet again
    scrape(folder, meta["settings"]["url"])
    meta, runs = runs_of(folder)
    assert len(runs) == before + 1, summary(runs)
