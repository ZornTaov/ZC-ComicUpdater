#a site whose every page carries two next links that disagree: one through the whole comic, by date, and one
#only through the pages of the same series - a weekly strip running beside a daily one. pages 3 and 7 are the
#weekly ones. the series link, found first, takes a run from page 3 straight to page 7 and on through the
#dailies from there, numbering everything as if nothing were missing. the comic's record of which page is
#which says what comes next, so the run puts itself right; and the path that worked last time is the one
#tried first.
import json

import pytest

from conftest import PNG, Site, pages_in, read_meta, run, write_index, write_meta

PAGES = 7
WEEKLY = {3, 7}
SERIES = '//a[@class="series-next"]'
WHOLE = '//a[@class="whole-next"]'
pytestmark = [pytest.mark.browser, pytest.mark.slow]


class TwoLinks(Site):
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG + self.path.encode(), "image/png")
            return
        number = self.path.rstrip("/").rsplit("/", 1)[-1]
        if not self.path.startswith("/c/") or not number.isdigit():
            self.send_error(404)
            return
        n = int(number)
        same = sorted(p for p in range(n + 1, PAGES + 1) if (p in WEEKLY) == (n in WEEKLY))
        links = ""
        if same:
            links += '<a class="series-next" href="/c/{0}">More like this</a>'.format(same[0])
        if n < PAGES:
            links += '<a class="whole-next" href="/c/{0}">Onward</a>'.format(n + 1)
        self.send('<html><head><title>Page {0}</title></head><body>{1}<div id="wrap">'
                  '<img id="cc-comic" width="240" height="240" src="/img/{0:04d}.png"></div></body></html>'
                  .format(n, links))


@pytest.fixture
def site(serve):
    return serve(TwoLinks)


def paths(config, *nexts):
    (config / "element_paths.json").write_text(json.dumps({"next": [{"xpath": x} for x in nexts]}),
                                               encoding="utf-8")


def held_to_three(site, library, chapters, remembered=None, index=True):
    #pages 1-3 saved, numbered; the comic resumes on page 3, the first weekly one
    out = library / "Uncompressed" / "Two"
    out.mkdir(parents=True)
    for n in range(1, 4):
        (out / "{0:04d}_{0:04d}.png".format(n)).write_bytes(PNG + "/img/{0:04d}.png".format(n).encode())
    write_meta(out, {"schema": 2, "settings": {"url": site + "/c/3", "output": "Uncompressed/Two", "increment": 3,
                                                "prefix": True, "cbz": False},
                     "state": {"next_xpath": remembered,
                               "last_image_url": site + "/img/0003.png", "last_image_file": "0003_0003.png"},
                     "history": {"first_page_url": site + "/c/1", "first_page_number": 1, "runs": []}})
    if index:
        #the whole comic, in reading order, as a list of the site's posts would give it, and named in the
        #comic's metadata as its own
        cache = chapters.index_path(str(out))
        meta = read_meta(out)
        meta["history"]["index_cache"] = cache.replace("\\", "/").rsplit("/", 1)[-1]
        write_meta(out, meta)
        write_index(cache, [
            {"n": n, "url": "{0}/c/{1}".format(site, n), "src": "{0}/img/{1:04d}.png".format(site, n),
             "file": "{0:04d}.png".format(n), "title": "Page {0}".format(n), "bytes": None} for n in range(1, 8)])
    return out


def resume(out, site):
    return run("mirror_base.py", "-o", out, "--no-cbz", "-p", "-i", "3", site + "/c/3")


def test_the_next_link_that_skips_is_put_right_from_the_record(site, library, chapters, config):
    paths(config, SERIES, WHOLE)
    out = held_to_three(site, library, chapters)
    done = resume(out, site)
    assert done.returncode == 0, done.stdout[-600:]
    assert "is used instead" in done.stdout
    assert pages_in(out) == ["{0:04d}_{0:04d}.png".format(n) for n in range(1, 8)], pages_in(out)
    assert read_meta(out)["state"]["next_xpath"] == WHOLE


def test_with_no_path_that_goes_to_the_next_page_it_stops_before_saving_past_it(site, library, chapters, config):
    paths(config, SERIES)
    out = held_to_three(site, library, chapters)
    done = resume(out, site)
    assert done.returncode == 10, done.stdout[-600:]
    assert "skips 3 page(s)" in done.stdout
    assert pages_in(out) == ["{0:04d}_{0:04d}.png".format(n) for n in range(1, 4)]
    #the next run starts where this one did, not past the pages it never fetched
    assert read_meta(out)["settings"]["url"] == site + "/c/3"


def test_the_path_that_worked_last_time_is_tried_first(site, library, chapters, config):
    #no record of which page is which to put it right: only the remembered path keeps the run on the comic
    paths(config, SERIES, WHOLE)
    out = held_to_three(site, library, chapters, remembered=WHOLE, index=False)
    done = resume(out, site)
    assert done.returncode == 0, done.stdout[-600:]
    assert pages_in(out) == ["{0:04d}_{0:04d}.png".format(n) for n in range(1, 8)], pages_in(out)
