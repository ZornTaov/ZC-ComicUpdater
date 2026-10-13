#a site whose newest page is a teaser locked for subscribers: no comic on it, only the header every page
#carries, whose logo sits inside an element with "comic" in its class. the comic's own path finds nothing
#there, the list is tried, and a loose path found the logo - saved as the newest page, and swapped for the
#next logo every time the site renamed it. a picture the page before showed anywhere is the site's own.
import json

import pytest

from conftest import PNG, Site, pages_in, read_meta, run, write_meta

IMAGE = '//*[@class="comicpage"]/a/img'
pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Locked(Site):
    #pages 1-3, and 4 a teaser with nothing but the header
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG + self.path.encode(), "image/png")
            return
        number = self.path.rstrip("/").rsplit("/", 1)[-1]
        if not self.path.startswith("/c/") or not number.isdigit():
            self.send_error(404)
            return
        n = int(number)
        header = '<div class="site comic-site comic"><img src="/img/logo.png"></div>'
        if n == 4:
            body = '<div class="locked">Become a subscriber to read this page early.</div>'
        else:
            body = ('<div class="comicpage"><a href="/c/{0}"><img width="240" height="240" src="/img/{1:04d}.png">'
                    '</a></div><a rel="next" href="/c/{0}">Next</a>').format(n + 1, n)
        self.send('<html><head><title>Page {0}</title></head><body>{1}{2}</body></html>'.format(n, header, body))


@pytest.fixture
def site(serve):
    return serve(Locked)


def test_a_locked_teaser_is_not_saved_as_the_newest_page(site, library, config):
    (config / "element_paths.json").write_text(json.dumps({"image": [{"xpath": IMAGE}]}), encoding="utf-8")
    out = library / "Uncompressed" / "Locked"
    out.mkdir(parents=True)
    for n in (1, 2):
        (out / "{0:04d}_{0:04d}.png".format(n)).write_bytes(PNG + "/img/{0:04d}.png".format(n).encode())
    write_meta(out, {"schema": 2, "settings": {"url": site + "/c/2", "output": "Uncompressed/Locked",
                                                "increment": 2, "prefix": True, "cbz": False},
                     "state": {"image_xpath": IMAGE, "last_image_url": site + "/img/0002.png",
                               "last_image_file": "0002_0002.png"},
                     "history": {"first_page_url": site + "/c/1", "first_page_number": 1, "runs": []}})
    done = run("mirror_base.py", "-o", out, "--no-cbz", "-p", "-i", "2", site + "/c/2")
    assert done.returncode == 0, done.stdout[-800:]
    assert pages_in(out) == ["0001_0001.png", "0002_0002.png", "0003_0003.png"], pages_in(out)
    #the next run carries on from the last real page, and finds page 4 once it is out - and says so, rather than
    #naming the teaser the browser was left on as where the run got to
    assert read_meta(out)["settings"]["url"] == site + "/c/3"
    said = "The next run carries on from {0}/c/3 (the browser stopped at {0}/c/4).".format(site)
    assert said in done.stdout, done.stdout[-600:]
