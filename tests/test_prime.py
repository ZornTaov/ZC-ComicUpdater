#--prime saves the first page of a comic and stops, leaving a comic update_comics can finish later; and the
#trigger file that starts an update before its scheduled time.
import threading
import time
from datetime import datetime, timedelta

import pytest

from conftest import Site, PNG, fresh, pages_in, read_meta, run

PAGES = 6


class Forward(Site):
    #/fwd/N runs from 1 to PAGES; any other kind of page has no next link at all
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        kind, _, number = self.path.lstrip("/").partition("/")
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        link = '<a href="/{0}/{1}">Next</a>'.format(kind, number + 1) if number < PAGES and kind == "fwd" else ""
        self.send('<html><body><div id="wrap">{1}<img id="cc-comic" src="/img/{0:04d}.png">'
                  '</div></body></html>'.format(number, link))


@pytest.fixture
def site(serve):
    return serve(Forward)


@pytest.mark.browser
@pytest.mark.slow
def test_prime_saves_one_page_and_update_comics_finishes_the_comic(site, library):
    comic = library / "Uncompressed" / "MyComic"
    done = run("mirror_base.py", "--prime", "-o", comic, site + "/fwd/1", timeout=240)
    assert done.returncode == 0, "{0}: {1}".format(done.returncode, done.stdout[-300:])
    assert pages_in(comic) == ["0001.png"]
    assert "Primed:" in done.stdout, done.stdout[-300:]
    meta = read_meta(comic)
    assert meta["settings"]["url"].endswith("/fwd/2"), meta["settings"]
    assert "prime" not in meta["settings"], "priming is how this run went, not a setting of the comic"
    assert meta["history"]["runs"][-1]["completed"] is False, meta["history"]["runs"][-1]
    assert (library / "CBZs" / "MyComic.cbz").is_file(), "the archive belongs on the CBZs shelf"

    #the primed comic is then an ordinary one to update_comics, which carries on from page 2
    done = run("update_comics.py", library, "--progress", "0", timeout=300)
    assert done.returncode == 0, done.stdout[-400:]
    assert pages_in(comic) == ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)], "no duplicates"
    assert "+5 page" in done.stdout, done.stdout[-400:]


@pytest.mark.browser
@pytest.mark.slow
def test_prime_on_a_single_page_comic_says_there_is_no_next_link(site, library):
    done = run("mirror_base.py", "--prime", "-o", library / "Uncompressed" / "Lone", site + "/fwd/6",
               timeout=240)
    assert "no next button" in done.stdout, done.stdout[-300:]


@pytest.fixture
def update(config):
    #the schedule's own module, looking for a trigger file five times a second rather than every half minute
    module = fresh("comiclib.schedule")
    module.trigger_poll = 0.2
    return module


def test_a_trigger_file_names_the_comics_to_update(update, library):
    assert update.take_trigger(str(library)) is None, "no file, no trigger"
    (library / "update-now.txt").write_text("", encoding="utf-8")
    assert update.take_trigger(str(library)) == [], "an empty file means everything"
    assert not (library / "update-now.txt").exists(), "the file is removed once read"
    #written the way notepad writes it: a byte order mark, and windows slashes
    (library / "update-now").write_text("# primed tonight\nUncompressed\\MyComic\n\n  Lone  \n",
                                        encoding="utf-8-sig")
    assert update.take_trigger(str(library)) == ["Uncompressed/MyComic", "Lone"], \
        "comments and blanks dropped, slashes fixed"


def test_waiting_for_the_schedule_returns_early_on_a_trigger(update, library):
    started = time.time()
    threading.Timer(0.5, lambda: (library / "update-now.txt").write_text("MyComic")).start()
    got = update.wait_until(datetime.now() + timedelta(hours=1), str(library))
    assert got == ["MyComic"] and time.time() - started < 3, (got, time.time() - started)
    assert update.wait_until(datetime.now() + timedelta(seconds=0.5), str(library)) is None, \
        "with no trigger, the wait ends at the scheduled time"
