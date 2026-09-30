#update_comics stopping a scrape that has run past its --timeout: the whole browser tree is killed on time,
#and the failure says what the scrape was doing when it was stopped.
import re
import time

import pytest

from conftest import Site, PNG, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Endless(Site):
    #a comic with no last page, each page a second slow, so a run can only end by being stopped
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        number = self.path.rsplit("/", 1)[-1]
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        time.sleep(1)
        self.send('<html><body><div id="wrap"><a href="/s/{1}">Next</a>'
                  '<img id="cc-comic" src="/img/{0:04d}.png"></div></body></html>'.format(number, number + 1))


def test_a_scrape_past_its_timeout_is_killed_on_time_and_says_what_it_was_doing(serve, library):
    site = serve(Endless)
    write_meta(library / "Uncompressed" / "MyComic",
               {"schema": 2, "settings": {"url": site + "/s/1", "output": "Uncompressed/MyComic",
                                          "increment": 1, "cbz": False}})
    started = time.time()
    done = run("update_comics.py", library, "--timeout", "8", "--progress", "0", timeout=120)
    took = time.time() - started
    assert "TIMED OUT" in done.stdout, done.stdout[-900:]
    assert took < 40, "took {0:.0f}s to stop a run given 8".format(took)
    assert "saving" in done.stdout, "the failure should show what it was doing:\n" + done.stdout[-900:]
    #the pages it saved before it was stopped are kept, and a timeout is no reason to leave them out
    assert re.search(r"TIMED OUT after \d+s, \+\d+ pages?", done.stdout), done.stdout[-900:]
    assert re.search(r"1 updated, 0 already current, 1 failed", done.stdout), done.stdout[-900:]
    assert re.search(r"MyComic +\+\d+ page\(s\), now \d+, then TIMED OUT", done.stdout), done.stdout[-900:]
