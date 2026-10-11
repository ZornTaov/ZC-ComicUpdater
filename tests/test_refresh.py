#a comic whose chapters were read off the site's archive page remembers that page, so its chapters can be
#read again with no arguments - and an update reads it again to take a chapter that began since. a chapter
#already written is never moved without --force. told not to read it, an update packs the new pages into the
#last chapter; one with no chapters yet reads it anyway. a comic cut every so many pages starts its next
#part on its own.
import json
import os
import zipfile

import pytest

from conftest import Site, PNG, read_meta, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


def make_site(pages, chapters):
    #the comic, and an archive page listing its chapters. both follow `state`, which a test changes to
    #have the site publish more
    state = {"pages": pages, "chapters": chapters, "banners": False}

    class Serial(Site):
        def do_GET(self):
            if self.path == "/archive":
                rows = []
                starts = dict((at, label) for label, at in state["chapters"])
                for n in range(1, state["pages"] + 1):
                    if n in starts:
                        #a banner drawn beside each chapter's name, as some sites head their chapters
                        banner = '<img src="banners/{0}.png"> '.format(n) if state["banners"] else ""
                        rows.append('<h3 class="comic-archive-chapter">{0}{1}</h3>'.format(banner, starts[n]))
                    rows.append('<a href="/p/{0}">page {0}</a>'.format(n))
                self.send("<html><body><h1>The Archive</h1>" + "".join(rows) + "</body></html>")
                return
            if self.path.startswith("/banners/"):
                #a site that serves its pictures only to its own pages
                if not (self.headers.get("Referer") or "").endswith("/archive"):
                    self.send_error(403)
                    return
                self.send(PNG, "image/png")
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


def hold(serve, library, config, chapters, pages, listed, steps=None):
    #the comic with `pages` held and indexed, its chapters read off the archive page and packed - or
    #whatever `steps` sets it up with instead
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
    from_archive = steps is None
    if from_archive:
        steps = (["align"], ["chapters", "--archive", site + "/archive", "--save"], ["pack"])
    for step in steps:
        done = run("chapters.py", step[0], comic, "--root", library, *step[1:], timeout=300)
        assert done.returncode == 0, "{0} failed in setting up:\n{1}".format(step[0], done.stdout[-400:])
    held = Held(site, state, library, config, comic)
    if from_archive:
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


def test_each_chapters_banner_is_saved_beside_its_archive_as_its_cover(serve, library, config, chapters):
    held = hold(serve, library, config, chapters, 12, THREE)
    assert not [name for name in os.listdir(str(held.out)) if name.endswith(".png")], "no banners on the page yet"
    #the site draws a banner over each chapter: reading the list again records them, and covers saves them
    #beside the archives already packed, packing nothing again
    held.state["banners"] = True
    done = held.chapters_cli("--save")
    assert done.returncode == 0 and "3 chapter(s) have a banner" in done.stdout, done.stdout[-400:]
    assert read_meta(held.comic)["chapters"]["list"][1]["image"] == held.site + "/banners/5.png"
    done = run("chapters.py", "covers", held.comic, "--root", library, timeout=300)
    assert done.returncode == 0, done.stdout[-400:]
    beside = sorted(name for name in os.listdir(str(held.out)) if name.endswith(".png"))
    assert beside == ["MyComic - c001 - One.png", "MyComic - c002 - Two.png", "MyComic - c003 - Three.png"], beside
    #one already there - a cover chosen in a reader - is never replaced
    (held.out / "MyComic - c002 - Two.png").write_bytes(b"chosen")
    run("chapters.py", "covers", held.comic, "--root", library, timeout=300)
    assert (held.out / "MyComic - c002 - Two.png").read_bytes() == b"chosen"


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


def update(held, *extra):
    return run("update_comics.py", held.library, "--progress", "0", "--config", held.config, *extra,
               timeout=900)


def test_an_update_leaves_the_archive_page_alone_when_told_not_to_read_it(serve, library, config, chapters):
    held = hold(serve, library, config, chapters, 12, THREE)
    held.state["pages"] = 16
    held.state["chapters"] = FOUR
    done = update(held, "--no-refresh-chapters")
    assert (held.comic / "0016.png").exists(), "the new pages should still be fetched:\n" + done.stdout[-500:]
    #chapter four is on the archive page, but nothing read it: the new pages join the chapter still being
    #published, and are packed there rather than left in no archive at all
    assert len(held.starts()) == 3, held.starts()
    assert "more than before" not in done.stdout, done.stdout[-500:]
    assert not any("c004" in name for name in os.listdir(str(held.out)))
    assert held.chapter(3) == ["{0:04d}.png".format(n) for n in range(9, 17)], held.chapter(3)


def test_a_comic_given_an_archive_page_before_any_chapters_gets_them_from_its_first_update(serve, library,
                                                                                         config, chapters):
    #as the web page leaves a comic it was given a chapter list for and only primed: the archive page is
    #written down, and no chapter has been worked out yet
    held = hold(serve, library, config, chapters, 12, THREE, steps=[["align"]])
    meta = read_meta(held.comic)
    meta["chapters"] = {"source": "archive", "source_url": held.site + "/archive", "list": []}
    write_meta(held.comic, meta)
    held.state["pages"] = 16
    held.state["chapters"] = FOUR
    done = update(held, "--no-refresh-chapters")
    #even with re-reading turned off, since there is nothing yet to keep
    assert held.starts() == [(1, "One", 1), (2, "Two", 5), (3, "Three", 9), (4, "Four", 13)], \
        held.starts() or done.stdout[-500:]
    assert sorted(os.listdir(str(held.out))) == ["MyComic - c00{0} - {1}.cbz".format(at, label)
                                                 for at, (label, _) in enumerate(FOUR, 1)]
    assert held.chapter(4) == ["0013.png", "0014.png", "0015.png", "0016.png"]
    assert not (library / "CBZs" / "MyComic.cbz").exists(), "a comic in chapters keeps no single archive"


def test_an_update_starts_the_next_part_of_a_comic_cut_every_so_many_pages(serve, library, config, chapters):
    #a comic with no chapters of its own, cut every four pages: the third part is half full
    held = hold(serve, library, config, chapters, 10, [], steps=[["align"], ["chapters", "--every", "4", "--save"],
                                                                 ["pack"]])
    assert held.starts() == [(1, "Pages 1-4", 1), (2, "Pages 5-8", 5), (3, "Pages 9-12", 9)]
    held.state["pages"] = 14
    #with re-reading archive pages off, which this reads nothing from the site for
    done = update(held, "--no-refresh-chapters")
    assert held.starts() == [(1, "Pages 1-4", 1), (2, "Pages 5-8", 5), (3, "Pages 9-12", 9),
                             (4, "Pages 13-16", 13)], held.starts() or done.stdout[-500:]
    assert "more than before" in done.stdout, done.stdout[-500:]
    #the third part filled under the name it already had, and the fourth began
    assert sorted(os.listdir(str(held.out))) == ["MyComic - c001 - Pages 1-4.cbz", "MyComic - c002 - Pages 5-8.cbz",
                                                 "MyComic - c003 - Pages 9-12.cbz",
                                                 "MyComic - c004 - Pages 13-16.cbz"]
    assert held.chapter(3) == ["0009.png", "0010.png", "0011.png", "0012.png"], held.chapter(3)
    assert held.chapter(4) == ["0013.png", "0014.png"], held.chapter(4)
    assert not (library / "CBZs" / "MyComic.cbz").exists(), "a comic in parts keeps no single archive"


def test_a_comic_cut_from_its_filenames_is_kept_in_parts_without_ever_being_walked(serve, library, config,
                                                                                  chapters):
    #the same comic, but with no record of which page is which: its files are numbered, which is enough
    held = hold(serve, library, config, chapters, 10, [], steps=[])
    os.remove(chapters.index_path(str(held.comic)))
    meta = read_meta(held.comic)
    meta["history"].pop("index_cache")
    write_meta(held.comic, meta)
    for step in (["chapters", "--every", "4", "--save"], ["pack"]):
        done = run("chapters.py", step[0], held.comic, "--root", library, *step[1:], timeout=300)
        assert done.returncode == 0, done.stdout[-400:]
    held.state["pages"] = 14
    done = update(held)
    assert held.starts()[-1] == (4, "Pages 13-16", 13), held.starts() or done.stdout[-500:]
    assert held.chapter(3) == ["0009.png", "0010.png", "0011.png", "0012.png"], held.chapter(3)
    assert held.chapter(4) == ["0013.png", "0014.png"], held.chapter(4)
    assert "said no" not in done.stdout, "nothing should have tried to line it up:\n" + done.stdout[-500:]
    #and it is still not walked: a scrape starts no record for a comic it is not scraping from page one
    assert not os.path.exists(chapters.index_path(str(held.comic)))
