#a site whose newest page carries a teaser for the page to come, linked to the page it is on, and no next link
#until that page is out. on the newest page the teaser is the only thing a next path matches, so it is what
#pressed, and what is remembered; the next day the real next link is there, but the remembered teaser is
#tried first, stays on the page, and the comic was called caught up while new pages came out. before calling
#it that, every other known next path is pressed, and one that goes on to a page not held is used instead.
import json

import pytest

from conftest import PNG, Site, pages_in, read_meta, run, write_meta

TEASER = '//a[@class="teaser"]'
FIRST = '//a[@class="back-to-start"]'
pytestmark = [pytest.mark.browser, pytest.mark.slow]


def comic_site(serve, latest):
    class Teasing(Site):
        def do_GET(self):
            if self.path.startswith("/img/"):
                self.send(PNG + self.path.encode(), "image/png")
                return
            number = self.path.rstrip("/").rsplit("/", 1)[-1]
            if not self.path.startswith("/c/") or not number.isdigit():
                self.send_error(404)
                return
            n = int(number)
            links = '<a class="teaser" href="/c/{0}">Coming soon</a>'.format(n)
            links += '<a class="back-to-start" href="/c/1">Start over</a>'
            if n < latest:
                links += '<a rel="next" href="/c/{0}">Next</a>'.format(n + 1)
            self.send('<html><head><title>Page {0}</title></head><body><div id="wrap"><img id="cc-comic" '
                      'width="240" height="240" src="/img/{0:04d}.png"></div>{1}</body></html>'.format(n, links))
    return serve(Teasing)


def paths(config, *nexts):
    (config / "element_paths.json").write_text(json.dumps({"next": [{"xpath": x} for x in nexts]}),
                                               encoding="utf-8")


def held_to_three(site, library):
    #pages 1-3 saved, the teaser remembered as the next button the day page 3 was the newest
    out = library / "Uncompressed" / "Teasing"
    out.mkdir(parents=True)
    for n in range(1, 4):
        (out / "{0:04d}_{0:04d}.png".format(n)).write_bytes(PNG + "/img/{0:04d}.png".format(n).encode())
    write_meta(out, {"schema": 2, "settings": {"url": site + "/c/3", "output": "Uncompressed/Teasing",
                                                "increment": 3, "prefix": True, "cbz": False},
                     "state": {"next_xpath": TEASER, "last_image_url": site + "/img/0003.png",
                               "last_image_file": "0003_0003.png"},
                     "history": {"first_page_url": site + "/c/1", "first_page_number": 1, "runs": []}})
    return out


def resume(out, site):
    return run("mirror_base.py", "-o", out, "--no-cbz", "-p", "-i", "3", site + "/c/3")


def test_a_remembered_teaser_does_not_hide_the_pages_that_came_out(serve, library, config):
    site = comic_site(serve, latest=5)
    paths(config, TEASER, FIRST)
    out = held_to_three(site, library)
    done = resume(out, site)
    assert done.returncode == 0, done.stdout[-800:]
    assert "goes on to {0}/c/4, a page not saved yet".format(site) in done.stdout, done.stdout[-800:]
    assert pages_in(out) == ["{0:04d}_{0:04d}.png".format(n) for n in range(1, 6)], pages_in(out)
    meta = read_meta(out)
    #and on page 5, where there is no next link yet, the comic is caught up as before - remembering the link
    #that went somewhere, not the teaser pressed last, so tomorrow's run starts from the right one
    assert meta["history"]["runs"][-1]["completed"] is True
    assert meta["state"]["next_xpath"] not in (TEASER, FIRST), meta["state"]["next_xpath"]


def test_a_comic_that_is_caught_up_stays_caught_up(serve, library, config):
    #the link back to the start goes to a page the comic holds, which is no newer page
    site = comic_site(serve, latest=3)
    paths(config, TEASER, FIRST)
    out = held_to_three(site, library)
    done = resume(out, site)
    assert done.returncode == 0, done.stdout[-800:]
    assert "a page not saved yet" not in done.stdout
    assert pages_in(out) == ["{0:04d}_{0:04d}.png".format(n) for n in range(1, 4)]
    assert "Caught up: pressing next goes to the same page" in done.stdout, done.stdout[-800:]
