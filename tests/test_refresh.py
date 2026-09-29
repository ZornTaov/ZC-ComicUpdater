#a comic whose chapters were read off the site's archive page remembers that page, so its chapters can be
#read again with no arguments - and an update reads it again to take a chapter that began since. a chapter
#already written is never moved without --force.
import json
import os
import zipfile

import pytest

from conftest import Site, PNG, read_meta, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


def make_site(pages, chapters):
    #the comic, and an archive page listing its chapters. both follow `state`, which a test changes to
    #have the site publish more
    state = {"pages": pages, "chapters": chapters}

    class Serial(Site):
        def do_GET(self):
            if self.path == "/archive":
                rows = []
                starts = dict((at, label) for label, at in state["chapters"])
                for n in range(1, state["pages"] + 1):
                    if n in starts:
                        rows.append('<h3 class="comic-archive-chapter">{0}</h3>'.format(starts[n]))
                    rows.append('<a href="/p/{0}">page {0}</a>'.format(n))
                self.send("<html><body><h1>The Archive</h1>" + "".join(rows) + "</body></html>")
                return
            bit = self.path.rsplit("/", 1)[-1].split(".")[0]
            if not bit.isdigit():
                self.send_error(404)
                return
            n = int(bit)
            if self.path.startswith("/img/"):
                self.send(PNG + bytes([n % 250]) * n, "image/png")
                return
            link = '<a href="/p/{0}">Next</a>'.format(n + 1) if n < state["pages"] else ""
            self.send('<html><head><title>Page {0}</title></head><body><div id="wrap">{1}'
                      '<img id="cc-comic" src="/img/{0:04d}.png"></div></body></html>'.format(n, link))

    return Serial, state


class Held:
    def __init__(self, site, state, library, config, comic):
        self.site, self.state, self.library, self.config, self.comic = site, state, library, config, comic
        self.out = library / "CBZs" / "MyComic"

    def starts(self):
        return [(c["number"], c["label"], c["start_page"]) for c in read_meta(self.comic)["chapters"]["list"]]

    def chapters_cli(self, *extra):
        return run("chapters.py", "chapters", self.comic, "--root", self.library, *extra, timeout=300)

    def pack(self):
        return run("chapters.py", "pack", self.comic, "--root", self.library, timeout=300)

    def chapter(self, number):
        name = [n for n in sorted(os.listdir(str(self.out))) if "c{0:03d}".format(number) in n][0]
        with zipfile.ZipFile(str(self.out / name)) as zf:
            return sorted(n for n in zf.namelist() if n.endswith(".png"))


def hold(serve, library, config, chapters, pages, listed):
    #the comic with `pages` held and indexed, its chapters read off the archive page and packed
    handler, state = make_site(pages, listed)
    site = serve(handler)
    comic = library / "Uncompressed" / "MyComic"
    comic.mkdir()
    for n in range(1, pages + 1):
        (comic / "{0:04d}.png".format(n)).write_bytes(PNG + bytes([n]) * n)
    index = chapters.index_path(str(comic))
    with open(index, "w", encoding="utf-8") as f:
        for n in range(1, pages + 1):
            f.write(json.dumps({"n": n, "url": "{0}/p/{1}".format(site, n),
                                "src": "{0}/img/{1:04d}.png".format(site, n), "file": "{0:04d}.png".format(n),
                                "title": "Page {0}".format(n), "bytes": len(PNG) + n}) + "\n")
    write_meta(comic, {
        "schema": 2,
        "settings": {"url": "{0}/p/{1}".format(site, pages), "output": "Uncompressed/MyComic",
                     "cbz_path": "CBZs/MyComic.cbz", "cbz": True, "increment": pages,
                     "direction_check": False},
        "history": {"runs": [], "index_cache": os.path.basename(index)}})
    for step in (["align"], ["chapters", "--archive", site + "/archive", "--save"], ["pack"]):
        done = run("chapters.py", step[0], comic, "--root", library, *step[1:], timeout=300)
        assert done.returncode == 0, "{0} failed in setting up:\n{1}".format(step[0], done.stdout[-400:])
    held = Held(site, state, library, config, comic)
    assert len(held.starts()) == len(listed)
    return held


THREE = [("One", 1), ("Two", 5), ("Three", 9)]
FOUR = THREE + [("Four", 13)]


def test_the_comic_remembers_where_its_chapters_are_listed(serve, library, config, chapters):
    held = hold(serve, library, config, chapters, 12, THREE)
    assert read_meta(held.comic)["chapters"]["source_url"] == held.site + "/archive"
    done = held.chapters_cli()
    assert "remembers" in done.stdout, "re-reading it should need no arguments:\n" + done.stdout[:200]
    assert "the same chapters as before" in done.stdout, done.stdout[-300:]


def test_an_update_finds_new_pages_that_began_a_new_chapter(serve, library, config, chapters):
    held = hold(serve, library, config, chapters, 12, THREE)
    held.state["pages"] = 16
    held.state["chapters"] = FOUR
    done = run("update_comics.py", library, "--progress", "0", "--config", config, timeout=900)
    assert len(held.starts()) == 4, held.starts()
    assert held.starts()[-1] == (4, "Four", 13), "the chapter should start where the archive says"
    assert "more than before" in done.stdout, "the run should say it gained a chapter:\n" + done.stdout[-500:]
    made = sorted(os.listdir(str(held.out)))
    assert any("c004" in name for name in made), "no archive was written for it: {0}".format(made)
    assert held.chapter(4) == ["0013.png", "0014.png", "0015.png", "0016.png"]
    assert held.chapter(3) == ["0009.png", "0010.png", "0011.png", "0012.png"], \
        "chapter three should no longer hold the new pages"


def test_an_archive_page_that_moves_a_written_chapter_is_refused_without_force(serve, library, config,
                                                                             chapters):
    #held as the update above leaves it: sixteen pages in four chapters
    held = hold(serve, library, config, chapters, 16, FOUR)
    was = held.starts()
    #chapter two now starts a page later
    held.state["chapters"] = [("One", 1), ("Two", 6), ("Three", 9), ("Four", 13)]
    done = held.chapters_cli("--save")
    assert done.returncode == 1 and "would move" in done.stdout, done.stdout[-400:]
    assert held.starts() == was, "nothing in the metadata should have changed"
    done = held.chapters_cli("--save", "--force")
    assert done.returncode == 0 and held.starts()[1] == (2, "Two", 6), held.starts()

    #and the archives follow once packed again
    held.pack()
    assert "0005.png" in held.chapter(1), "the page that moved should be in chapter one now"
