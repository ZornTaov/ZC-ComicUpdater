#putting a page into a comic by hand: a page the site has but the comic's own next links skip. the page is
#fetched the way a scrape fetches it, in a real browser, and every page after it moves one place along.
import os

import pytest

from conftest import Site, read_meta, run, write_index, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Toy(Site):
    #a tiny comic site, so the insert fetches a real page over http the way it will in earnest
    def do_GET(self):
        if self.path.endswith(".png"):
            self.send(b"IMAGE-" + self.path.encode(), "image/png")
            return
        name = self.path.strip("/") or "p1"
        self.send("<html><head><title>Toy - {0}</title></head><body>"
                  "<img id='cc-comic' src='/img/{0}.png'></body></html>".format(name))


def image(name):
    return "IMAGE-/img/{0}.png".format(name).encode()


class Comic:
    def __init__(self, library, folder, base, cache):
        self.library = library
        self.folder = folder
        self.base = base
        self.cache = cache

    def insert(self, url, after, *extra):
        done = run("chapters.py", "insert", self.folder, "--root", self.library, "--url", self.base + url,
                   "--after", after, *extra)
        return done.returncode, done.stdout + done.stderr

    def align(self):
        done = run("chapters.py", "align", self.folder, "--root", self.library)
        return done.stdout + done.stderr

    def pages(self):
        return sorted(f for f in os.listdir(str(self.folder)) if f.endswith(".png"))


@pytest.fixture
def toy(library, chapters, serve):
    #six pages held, numbered; the site also has a seventh the comic's links skip, between 3 and 4
    base = serve(Toy)
    folder = library / "Uncompressed" / "Toy"
    folder.mkdir()
    urls = ["{0}/p{1}".format(base, n) for n in range(1, 7)]
    for at in range(1, 7):
        (folder / "{0:04d}_p{1}.png".format(at, at)).write_bytes(image("p{0}".format(at)))
    write_meta(folder, {"settings": {"url": urls[-1], "prefix": True}, "history": {}})
    cache = chapters.index_path(str(folder), str(library), None)
    write_index(cache, [{"n": at, "url": url, "src": "{0}/img/p{1}.png".format(base, at),
                         "file": "p{0}.png".format(at), "title": "Toy - p{0}".format(at),
                         "bytes": len(image("p{0}".format(at)))} for at, url in enumerate(urls, 1)])
    comic = Comic(library, folder, base, cache)
    comic.align()
    return comic


def test_a_dry_run_says_where_it_would_go_and_moves_nothing(toy):
    was = sorted(os.listdir(str(toy.folder)))
    code, out = toy.insert("/p3a", "3", "--dry-run")
    assert code == 0 and "goes in at page 4" in out, [l for l in out.splitlines() if "goes in" in l]
    assert sorted(os.listdir(str(toy.folder))) == was


def test_putting_a_page_in_moves_the_rest_along(toy, chapters):
    code, out = toy.insert("/p3a", "3")
    assert code == 0, out.strip().splitlines()[-4:]
    held = toy.pages()
    assert len(held) == 7, held
    assert any(f.startswith("0004_") and "p3a" in f for f in held), held
    assert [f.split("_")[0] for f in held] == ["0001", "0002", "0003", "0004", "0005", "0006", "0007"], held
    #nothing was written over
    assert sorted((toy.folder / f).read_bytes() for f in held) == \
        sorted([image("p3a")] + [image("p{0}".format(n)) for n in range(1, 7)]), \
        [(toy.folder / f).read_bytes()[:20] for f in held]
    lines = chapters.read_index(toy.cache)
    #the walk's record holds it too, in order, at the right place, and the records after it point at their
    #new names
    assert [l["n"] for l in lines] == list(range(1, 8)), [l["n"] for l in lines]
    assert lines[3]["url"].endswith("/p3a"), lines[3]["url"]
    assert lines[4]["file"] == "0005_p4.png", lines[4]["file"]
    out = toy.align()
    assert "settled" in out and "NOT settled" not in out, out.strip().splitlines()[-2:]
    inserted = read_meta(toy.folder)["history"].get("inserted")
    #and it is written down as put in by hand
    assert (inserted or [{}])[0].get("page") == 4, inserted


def test_asking_twice_puts_nothing_in_again(toy):
    toy.insert("/p3a", "3")
    code, out = toy.insert("/p3a", "3")
    assert code == 0 and "already holds" in out, out.strip().splitlines()[:2]
    assert len(toy.pages()) == 7, toy.pages()


def test_a_page_number_the_comic_does_not_have_is_refused(toy):
    code, out = toy.insert("/p9", "99")
    assert code == 2 and "not a page of this comic" in out, out.strip().splitlines()[:2]
