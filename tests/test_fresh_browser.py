#a browser led through thousands of pages in one tab slows to a crawl and then stops loading them properly, so a
#walk or a scrape hands over to a fresh one every so many pages. here every three, so a short comic shows it:
#the pages after each hand-over are read in order, none twice and none missed, and a cookie the site set
#earlier is still there afterwards.
import json

import pytest

from conftest import PNG_240, Comic, comic_page, pages_in, run

PAGES = 10
EVERY = {"MIRROR_RENEW_EVERY": "3"}


class Long(Comic):
    pages = PAGES


class AgeCheck(Comic):
    #a comic that shows its pages only to a browser holding the cookie its first page sets - the way a site
    #asks once whether the reader is old enough. without it, a page has no comic and no next link
    pages = PAGES

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/img/"):
            self.send(PNG_240, "image/png")
            return
        number = int(path.rsplit("/", 1)[-1])
        allowed = "old_enough=yes" in (self.headers.get("Cookie") or "")
        if number > 1 and not allowed:
            body = "<html><head><title>How old are you?</title></head><body>Please confirm.</body></html>"
        else:
            body = self.page(number)
        body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        if number == 1:
            self.send_header("Set-Cookie", "old_enough=yes; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < self.pages else None
        return comic_page("/img/{0:04d}.png".format(number), onward, "Comic {0}".format(number))


def walked(index):
    with open(str(index), encoding="utf-8") as f:
        return [json.loads(text)["url"].rsplit("/", 1)[-1] for text in f if text.strip()]


@pytest.mark.browser
def test_a_walk_hands_over_to_a_fresh_browser_and_misses_nothing(tmp_path, serve):
    site = serve(Long)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, site + "/p/1", cwd=tmp_path, env=EVERY)
    assert done.returncode == 0, done.stdout[-600:]
    assert walked(index) == [str(n) for n in range(1, PAGES + 1)], "every page once, in order"
    assert done.stdout.count("A fresh browser after") == 3, done.stdout[-600:]


@pytest.mark.browser
def test_a_scrape_hands_over_to_a_fresh_browser_and_saves_every_page(tmp_path, serve):
    site = serve(Long)
    out = tmp_path / "comic"
    done = run("mirror_base.py", "-o", out, "--no-cbz", site + "/p/1", cwd=tmp_path, env=EVERY)
    assert done.returncode == 0, done.stdout[-600:]
    assert pages_in(out) == ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)], done.stdout[-600:]
    assert "A fresh browser after 3 pages" in done.stdout


@pytest.mark.browser
def test_a_fresh_browser_keeps_the_cookies_the_site_set(tmp_path, serve):
    site = serve(AgeCheck)
    index = tmp_path / "walk.jsonl"
    #a fresh profile for each browser, as a real run has: a profile shared from the test pool would carry the
    #cookie from one browser to the next by itself, and this would pass whether the hand-over kept it or not
    done = run("mirror_base.py", "--index", index, site + "/p/1", cwd=tmp_path,
               env=dict(EVERY, MIRROR_PROFILE_POOL=""))
    assert done.returncode == 0, done.stdout[-600:]
    assert walked(index) == [str(n) for n in range(1, PAGES + 1)], \
        "without the cookie the page after a hand-over has no comic and no next link"
