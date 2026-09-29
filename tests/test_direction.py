#a next link that runs backwards looks page by page exactly like one that works: every address is new. what
#tells the two apart is which way the pages already held go - a re-scrape from an earlier point walks
#forward over them, a backwards link walks back down them.
import pytest

from conftest import PNG, Site, pages_in, run

PAGES = 6
pytestmark = [pytest.mark.browser, pytest.mark.slow]


def html(img, onward):
    link = '<a href="{0}">Next</a>'.format(onward) if onward else ''
    return ('<html><body><div id="wrap">{1}'
            '<img id="cc-comic" src="{0}"></div></body></html>'.format(img, link))


class TwoWays(Site):
    #a comic of six pages. /fwd/N goes on to N+1, a normal comic whose images are plainly numbered.
    #/rev/N goes to N-1, the shape of a site whose next link runs backwards
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        kind, _, number = self.path.lstrip("/").partition("/")
        if kind not in ("fwd", "rev") or not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        onward = number + (1 if kind == "fwd" else -1)
        self.send(html("/img/{0:04d}.png".format(number),
                       "/{0}/{1}".format(kind, onward) if 1 <= onward <= PAGES else None))


@pytest.fixture
def site(serve):
    return serve(TwoWays)


def seed(folder, names):
    #the site's own bytes: a held page that differs from what the site serves under the same name is a
    #site reusing its filenames, which is a different guard altogether
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(PNG)
    return folder


def scrape(tmp_path, out, url, *extra):
    return run("mirror_base.py", "-o", out, "--no-cbz", *extra, url, cwd=tmp_path, timeout=240)


def test_a_forward_rescrape_over_pages_already_held_is_not_called_backwards(tmp_path, site):
    out = seed(tmp_path / "fwd", ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)])
    done = scrape(tmp_path, out, site + "/fwd/2")
    assert done.returncode == 0, "{0}: {1}".format(done.returncode, done.stdout.strip()[-250:])
    assert "backwards" not in done.stdout, done.stdout.strip()[-250:]
    assert "0006.png" in done.stdout, "did not walk all the way to page 6: " + done.stdout.strip()[-200:]


def test_a_next_link_running_backwards_over_pages_already_held_stops_the_run(tmp_path, site):
    out = seed(tmp_path / "rev", ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)])
    done = scrape(tmp_path, out, site + "/rev/5")
    #one step back is not evidence - a comic that numbers each chapter from one takes exactly one - so the
    #run stops at the second step in a row: 5, then 4, then 3
    assert done.returncode == 8, "{0}: {1}".format(done.returncode, done.stdout.strip()[-250:])
    assert "page 3 of this comic and the page before it was 4" in done.stdout, done.stdout.strip()[-250:]


def test_a_fresh_comic_with_nothing_held_is_never_blocked(tmp_path, site):
    out = tmp_path / "new"
    done = scrape(tmp_path, out, site + "/fwd/1")
    saved = pages_in(out)
    assert len(saved) == PAGES, saved
    assert done.returncode == 0, done.stdout.strip()[-250:]


def test_a_backwards_link_is_caught_with_prefixed_names_too(tmp_path, site):
    #the site serves /img/000N.png, so a prefixed save lands as 000M_000N.png; what is held carries the
    #same page keys under the older doubled extension
    out = seed(tmp_path / "pre", ["{0:04d}_{0:04d}.png.png".format(n) for n in range(1, PAGES + 1)])
    done = scrape(tmp_path, out, site + "/rev/5", "-p", "-i", "5")
    assert done.returncode == 8, "{0}: {1}".format(done.returncode, done.stdout.strip()[-300:])
