#a comic's settings edited from the web page: read, refused when wrong or stale, saved and updated from,
#brought up from an older schema, and left alone while it is being scraped.
import json
import shutil
import time

import pytest

from conftest import PNG, Site, console_errors, open_page, pages_in, read_meta, run, wait_until, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]
LAST = 8


class Broken(Site):
    #pages 1-3 link on, page 3's next link is broken (it goes to a page with no image), and the story
    #actually carries on at /c/5 through /c/8. a subclass with `slow` set takes its time from page 5 on,
    #so a run over them can be caught while it is going
    slow = False

    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        number = self.path.rsplit("/", 1)[-1]
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        if self.slow and number >= 5:
            time.sleep(1.0)
        if number == 4:
            self.send("<html><body><p>broken page</p></body></html>")
            return
        link = '<a href="/c/{0}">Next</a>'.format(number + 1) if number < LAST else ""
        self.send('<html><body><div id="wrap">{1}<img id="cc-comic" src="/img/{0:04d}.png">'
                  '</div></body></html>'.format(number, link))


class SlowBroken(Broken):
    slow = True


NAME = "Uncompressed/MyComic"


@pytest.fixture
def scraped(serve, library, tmp_path):
    #scraped until the broken page, the way the comic would be found in a library
    site = serve(Broken)
    comic = library / "Uncompressed" / "MyComic"
    run("mirror_base.py", "-o", comic, site + "/c/1", cwd=tmp_path)
    return site, comic


def test_reading_a_comic_and_refusing_bad_edits(scraped, web):
    site, comic = scraped
    page = web()
    code, detail = page.call("/api/comic?name=" + NAME)
    assert code == 200, detail
    #a next link to a page with no comic on it reads as the comic going no further for now, so the run
    #ends cleanly on the last good page rather than failing on the broken one
    last = detail["runs"][0]
    assert last["exit_code"] == 0 and last["stop_reason"] == "the next link led off the comic", last
    assert detail["settings"]["url"].endswith("/c/3"), detail["settings"]["url"]
    assert detail["pages_in_folder"] == 3, detail
    assert page.call("/api/comic?name=Nope")[0] == 404

    before = (comic / "mirror_metadata.json").read_text(encoding="utf-8")
    code, answer = page.call("/api/settings", {"name": NAME, "updated": detail["updated"],
                                               "settings": {"url": "not a url", "increment": "-3"}})
    assert code == 400 and "http" in answer["error"] and "increment" in answer["error"], answer
    #an edit made against a copy older than the file would undo whatever changed it since
    code, answer = page.call("/api/settings", {"name": NAME, "updated": "2000-01-01T00:00:00Z",
                                               "settings": {"url": site + "/c/5"}})
    assert code == 409, answer
    assert (comic / "mirror_metadata.json").read_text(encoding="utf-8") == before


def test_pointing_a_comic_past_a_broken_page_and_updating(scraped, web):
    site, comic = scraped
    page = web()
    _, detail = page.call("/api/comic?name=" + NAME)
    shutil.copy(str(comic / "0003.png"), str(comic / "0004.png"))  # the page found by hand
    code, answer = page.call("/api/settings", {"name": NAME, "updated": detail["updated"], "update_after": True,
                                               "settings": dict(detail["settings"], url=site + "/c/5",
                                                                increment=5)})
    assert code == 200 and answer["saved"] and answer.get("queued"), answer
    assert set(answer["changed"]) == {"url", "increment"}, answer
    assert "output" not in answer["changed"]
    assert page.wait_idle(120), "the update never finished"
    assert pages_in(comic) == ["{0:04d}.png".format(n) for n in range(1, LAST + 1)]
    meta = read_meta(comic)
    assert len(meta["history"].get("edits", [])) == 1, "the run should keep the edit log: {0}".format(
        list(meta["history"].keys()))
    #the run's own first page is still the comic's first page, not where the edit pointed it
    assert meta["history"]["first_page_url"].endswith("/c/1"), meta["history"]


def test_an_older_comic_is_brought_up_to_date_and_is_not_edited_while_running(serve, library, web):
    site = serve(SlowBroken)
    old = library / "Uncompressed" / "Old"
    old.mkdir(parents=True)
    (old / "0001.png").write_bytes(PNG)
    with open(old / "mirror_metadata.json", "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "resume_argv": ["--increment", "1", "--output", "Uncompressed/Old", site + "/c/1"],
                   "resume_command_line": "python mirror_base.py --increment 1 --output Uncompressed/Old "
                                          + site + "/c/1",
                   "runs": [{"run_id": "x", "command_line": "old", "stop_reason": "no next button",
                             "exit_code": 0}]}, f)
    page = web()

    code, detail = page.call("/api/comic?name=Uncompressed/Old")
    assert code == 200 and detail["settings"]["url"].endswith("/c/1"), detail
    code, answer = page.call("/api/settings", {"name": "Uncompressed/Old", "updated": detail["updated"],
                                               "settings": dict(detail["settings"], ended=True)})
    meta = read_meta(old)
    assert code == 200 and meta["schema"] == 2 and meta["settings"]["ended"] is True, (answer, meta)
    assert not [p.name for p in old.iterdir() if p.name.endswith(".editing")]
    assert page.call("/api/settings", {"name": "Uncompressed/Old",
                                       "settings": {"ended": True}})[1].get("saved") is False, \
        "an edit that changes nothing should say so"

    #now a comic being scraped: its settings cannot be edited under the run
    write_meta(old, dict(meta, settings=dict(meta["settings"], ended=False, url=site + "/c/5")))
    page.call("/api/update", {"names": ["Uncompressed/Old"]})
    running = False
    for _ in range(80):
        _, state = page.call("/api/state")
        if state["current"] and any(c["state"] == "running" for c in state["current"].get("comics", [])):
            running = True
            break
        time.sleep(0.25)
    try:
        _, detail = page.call("/api/comic?name=Uncompressed/Old")
        assert running and detail["running"] is True, detail.get("running")
        code, answer = page.call("/api/settings", {"name": "Uncompressed/Old", "settings": {"url": site + "/c/1"}})
        assert code == 409, answer
    finally:
        page.call("/api/stop", {})
        page.wait_idle()


def test_the_editor_opens_without_console_errors(scraped, web, browser):
    page = web()
    for width, height in ((1300, 950), (420, 1100)):
        browser.set_window_size(width, height)
        open_page(browser, page.base + "/")
        #the library table is filled in by a fetch after the page loads
        wait_until(lambda: browser.execute_script(
            "return document.querySelector('[data-edit=\"{0}\"]')".format(NAME)), why="the comic never listed")
        browser.execute_script("document.querySelector('[data-edit=\"{0}\"]').click()".format(NAME))
        time.sleep(1)
        browser.execute_script("document.getElementById('edit-runs-box').open = true")
        time.sleep(0.3)
    errors = console_errors(browser)
    assert not errors, errors
