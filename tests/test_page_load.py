#a page that does not load - a connection dropped, a site refusing for a while - leaves the browser showing an
#error page of its own, with an image on it and no next link. read as a page of the comic that is the comic's
#last, which ended two walks thousands of pages early. it is tried again, and a run it never loads for stops
#with the code for a page that would not load, rather than marking the comic caught up. the waits between
#tries are cut to a fraction of a second here, so these take no longer than any other test.
import json
import time

import pytest

from conftest import Comic, pages_in, read_meta, run

PAGES = 6
QUICK = {"MIRROR_RETRY_WAITS": "0.1,0.1"}


class Dropping(Comic):
    #page 4 drops every connection without a word for `down` seconds from the first time it is asked for,
    #then answers - the shape of a site that is briefly unreachable. by time and not by count, since chrome
    #quietly asks again itself, a number of times of its own choosing, before it shows an error page at all
    pages = PAGES
    down = 0.5
    since = None

    def do_GET(self):
        if self.path.split("?")[0] == "/p/4":
            cls = type(self)
            cls.since = cls.since or time.monotonic()
            if time.monotonic() - cls.since < cls.down:
                self.close_connection = True
                return
        Comic.do_GET(self)


class NeverLoads(Dropping):
    down = 10 ** 6


def walked(index):
    with open(str(index), encoding="utf-8") as f:
        return [json.loads(text)["url"].rsplit("/", 1)[-1] for text in f if text.strip()]


@pytest.mark.browser
def test_a_page_that_fails_once_is_loaded_again_and_the_walk_goes_on(tmp_path, serve):
    site = serve(Dropping)
    index = tmp_path / "walk.jsonl"
    #a second between tries, so the first try comes after the half second the page is down for
    done = run("mirror_base.py", "--index", index, site + "/p/1", cwd=tmp_path, env={"MIRROR_RETRY_WAITS": "1,1"})
    assert done.returncode == 0, done.stdout[-600:]
    assert "did not load" in done.stdout, done.stdout[-600:]
    assert walked(index) == [str(n) for n in range(1, PAGES + 1)], "every page, the one that failed included"


@pytest.mark.browser
def test_a_walk_stops_at_a_page_that_never_loads_rather_than_calling_it_the_last(tmp_path, serve):
    site = serve(NeverLoads)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, site + "/p/1", cwd=tmp_path, env=QUICK)
    assert done.returncode == 6, "the code for a page that would not load\n" + done.stdout[-600:]
    assert "would not load" in done.stdout, done.stdout[-600:]
    assert "latest page" not in done.stdout, "a page that never loaded is not the comic's last"
    assert walked(index) == ["1", "2", "3"], "and the browser's error page is not in the index as a page"


@pytest.mark.browser
def test_a_scrape_stops_at_a_page_that_never_loads_without_calling_the_comic_caught_up(tmp_path, serve):
    site = serve(NeverLoads)
    out = tmp_path / "comic"
    done = run("mirror_base.py", "-o", out, "--no-cbz", site + "/p/1", cwd=tmp_path, env=QUICK)
    assert done.returncode == 6, done.stdout[-600:]
    assert pages_in(out) == ["0001.png", "0002.png", "0003.png"], "nothing saved from the error page"
    state = read_meta(out)["state"]
    assert not state.get("completed"), "a run cut short is not one that reached the latest page"
