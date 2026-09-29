#the guards a real scrape runs into: a next link that doubles back onto a page already held, a page the
#folder holds under an older spelling of its name, and a next link that climbs out of the comic.
import pytest

from conftest import PNG, Site, run

pytestmark = [pytest.mark.browser, pytest.mark.slow]


def page(img, onward, label):
    link = '<a href="{0}">Next</a>'.format(onward) if onward else ''
    return ('<html><body><div id="wrap">{2}'
            '<img id="cc-comic" src="{0}">'
            '</div><p>{1}</p></body></html>'.format(img, label, link))


#/comic/p1 and /comic/p2 point at each other; /deep/v2 has a next that climbs out to /front.php
ROUTES = {
    "/comic/p2": page("/img/b.png", "/comic/p1", "p2, next goes BACKWARDS to p1"),
    "/comic/p1": page("/img/a.png", "/comic/p2", "p1"),
    "/deep/v2": page("/img/c.png", "/front.php", "v2, next climbs out"),
    "/front.php": "<html><body><h1>front page, no comic here</h1></body></html>",
}


class Guarded(Site):
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        body = ROUTES.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send(body)


@pytest.fixture
def site(serve):
    return serve(Guarded)


def scrape(tmp_path, out, url, *extra):
    return run("mirror_base.py", "-p", "-o", out, "--no-cbz", *extra, url, cwd=tmp_path, timeout=240)


def test_a_single_step_back_onto_a_held_page_is_not_taken_for_a_backwards_link(tmp_path, site):
    #one step back is exactly what a comic numbering each chapter from one looks like at every chapter
    #boundary, so it is let through; a link that really runs backwards keeps going back, and that is
    #caught (test_direction). a two-page loop like this one ends on the loop check instead
    out = tmp_path / "back"
    out.mkdir()
    (out / "0001_a.png.png").write_bytes(b"already have this one")
    done = scrape(tmp_path, out, site + "/comic/p2", "-i", "2")
    files = sorted(p.name for p in out.iterdir())
    assert done.returncode == 0, "{0}: {1}".format(done.returncode, done.stdout.strip()[-200:])
    assert "going backwards" not in done.stdout, done.stdout.strip()[-200:]
    assert "looped" in done.stdout, done.stdout.strip()[-200:]
    assert any(f.startswith("0002_b") for f in files), "lost the page it did fetch: {0}".format(files)


@pytest.mark.parametrize("seeded", ["0002_b.png.png", "0002.png"],
                         ids=["extension appended twice", "hand renumbered to digits"])
def test_a_resume_page_held_under_an_older_name_is_held_once_under_the_new_one(tmp_path, site, seeded):
    out = tmp_path / "dupe"
    out.mkdir()
    (out / seeded).write_bytes(b"older spelling")
    #the direction check is off so the run ends on the loop between the two pages rather than on the guard
    scrape(tmp_path, out, site + "/comic/p2", "-i", "2", "--no-direction-check")
    pages = sorted(p.name for p in out.iterdir() if p.name != "mirror_metadata.json")
    assert seeded not in pages, "the old name is still there: {0}".format(pages)
    assert "0002_b.png" in pages, "the new name was not kept: {0}".format(pages)
    assert len([f for f in pages if f.startswith("0002")]) == 1, "the page is held twice: {0}".format(pages)


def test_a_next_link_to_the_front_page_ends_the_run_cleanly(tmp_path, site):
    #climbing out of the comic has no special case: the link is followed, and a page with no comic on it,
    #reached after pages were saved, is the comic running out rather than the site breaking
    out = tmp_path / "end"
    done = scrape(tmp_path, out, site + "/deep/v2", "-i", "5")
    assert done.returncode == 0, "{0}: {1}".format(done.returncode, done.stdout.strip()[-200:])
    assert "as far as the comic goes for now" in done.stdout, done.stdout.strip()[-200:]
    assert "leaves the comic" not in done.stdout, done.stdout.strip()[-200:]
    assert (out / "0005_c.png").is_file(), sorted(p.name for p in out.iterdir())
