#the web page's api over a library: the password and what it accepts, adding comics, updating them, and a
#job queue that can be watched, stopped and pruned while it runs.
import time

import pytest

from conftest import PNG, Site, console_errors, open_page, pages_in, read_meta, wait_until

PASSWORD = "hunter2"
PAGES = 6
SLOW_PAGES = 40


class Linked(Site):
    #/fwd/N has PAGES pages; /slow/N has more, and each takes a while, so a run can be caught and stopped.
    #the next link comes before the image and is only known by its text
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        kind, _, number = self.path.lstrip("/").partition("/")
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        pages = SLOW_PAGES if kind == "slow" else PAGES
        if kind == "slow":
            time.sleep(1.0)
        link = '<a href="/{0}/{1}">Next</a>'.format(kind, number + 1) if number < pages else ""
        self.send('<html><body><div id="wrap">{2}<img id="cc-comic" src="/img/{0}{1:04d}.png">'
                  '</div></body></html>'.format(kind, number, link))


@pytest.fixture
def site(serve):
    return serve(Linked)


@pytest.fixture
def page(web):
    return web(password=PASSWORD, extra=("--jobs", "2"))


def test_the_api_wants_the_password_and_json(page):
    assert page.call("/api/state", auth=False)[0] == 401
    assert b"Comic Updater" in page.call("/")[1]
    #a form post is what a page on another site could make a browser send, so only json is taken
    assert page.call("/api/update", {}, ctype="application/x-www-form-urlencoded")[0] == 415


def test_an_add_with_bad_rows_is_refused_whole(page, site, library):
    code, answer = page.call("/api/add", {"rows": [{"folder": "A", "url": site + "/fwd/1"},
                                                   {"folder": "../escape", "url": site + "/fwd/1"},
                                                   {"folder": "NoUrl", "url": "not a url"}]})
    assert code == 400 and "row 2" in answer["error"] and "row 3" in answer["error"], answer
    assert not (library / "Uncompressed" / "A").exists()


@pytest.mark.browser
@pytest.mark.slow
def test_priming_two_comics_then_updating_them(page, site, library):
    group = library / "Uncompressed" / "Group"
    code, answer = page.call("/api/add", {"rows": [{"folder": "Group/One", "url": site + "/fwd/1"},
                                                   {"folder": "Group/Two", "url": site + "/fwd/1"}],
                                          "prime": True})
    assert code == 200, answer
    state = page.wait_idle()
    assert state, "the priming never finished"
    assert [len(pages_in(group / name)) for name in ("One", "Two")] == [1, 1], state["history"][:1]
    assert state["history"][0]["label"] == "Prime 2 new comics", state["history"][:1]

    _, rows = page.call("/api/comics")
    assert sorted(row["name"] for row in rows) == ["Uncompressed/Group/One", "Uncompressed/Group/Two"], rows
    assert page.call("/api/add", {"rows": [{"folder": "Group/One", "url": site + "/fwd/1"}]})[0] == 400, \
        "adding a comic that already exists should be refused"
    assert page.call("/api/add", {"rows": [{"folder": "Twice", "url": site + "/fwd/1"},
                                           {"folder": "Twice", "url": site + "/fwd/1"}]})[0] == 400, \
        "the same folder twice in one batch should be refused"
    #a comic already in a group has its archive beside its siblings: CBZs/<group>/<comic>.cbz
    shelf = library / "CBZs" / "Group"
    assert (shelf / "One.cbz").is_file(), list(shelf.iterdir())

    code, answer = page.call("/api/update", {"names": ["Uncompressed/Group/*"]})
    assert code == 200, answer
    state = page.wait_idle()
    assert state, "the update never finished"
    assert [len(pages_in(group / name)) for name in ("One", "Two")] == [PAGES, PAGES]
    assert state["history"][0].get("gained") == 2 * (PAGES - 1), state["history"][0]
    assert sorted(p.name for p in shelf.iterdir()) == ["One.cbz", "Two.cbz"]

    #the page's own log carries the run summaries, and the container log still gets them too
    _, state = page.call("/api/state?since=0")
    text = "\n".join(line["text"] for line in state["log"])
    assert "Finished in" in text and "Queued:" in text, text[-500:]
    assert "Finished in" in page.said()


@pytest.mark.browser
@pytest.mark.slow
def test_a_running_scrape_can_be_watched_and_stopped_and_a_queued_job_dropped(page, site, library):
    page.call("/api/add", {"rows": [{"folder": "Slow", "url": site + "/slow/1"}]})
    page.call("/api/update", {"names": []})
    seen = state = None
    for _ in range(80):
        _, state = page.call("/api/state")
        current = state["current"]
        if current and current.get("comics") and current["comics"][0].get("last_line") \
                and current["comics"][0]["gained"] >= 2:
            seen = state
            break
        time.sleep(0.25)
    assert seen is not None, "the running comic never showed its progress and last line: {0}".format(state)
    assert len(seen["waiting"]) == 1, seen["waiting"]
    assert page.call("/api/drop", {"id": seen["waiting"][0]["id"]})[1]["dropped"] is True
    assert page.call("/api/stop", {})[1]["stopping"] is True

    state = page.wait_idle(60)
    assert state, "the stop never took"
    slow = library / "Uncompressed" / "Slow"
    held = len(pages_in(slow))
    assert 0 < held < SLOW_PAGES, "stopped part way, with the pages kept: {0}".format(held)
    assert state["history"][0]["counts"].get("stopped") == 1, state["history"][0]
    url = read_meta(slow)["settings"]["url"]
    assert url.endswith("/slow/{0}".format(held + 1)) or url.endswith("/slow/{0}".format(held)), (held, url)
    labels = [job["label"] for job in state["history"]]
    assert "Started from the web page: every comic" not in labels, "the dropped job ran: {0}".format(labels)


@pytest.mark.browser
@pytest.mark.slow
def test_a_run_opened_under_recent_stays_open(page, site, browser):
    #the page redraws what it is shown every poll, and a run's list of comics opened under Recent closed
    #again on the next one. it has to stay open through a poll that changes nothing and through one where
    #another job has finished above it
    page.call("/api/add", {"rows": [{"folder": "Kept", "url": site + "/fwd/1"}], "prime": True})
    assert page.wait_idle(), "the priming never finished"
    open_page(browser, page.base.replace("http://", "http://me:{0}@".format(PASSWORD)) + "/")
    wait_until(lambda: browser.execute_script("return document.querySelector('#history details')"),
               why="the finished run never showed under Recent")
    browser.execute_script("document.querySelector('#history details').open = true")
    #a poll as the page makes one, with an extra argument that puts a newer job in front of the history
    redraw = ("const done = arguments[arguments.length - 1], newer = arguments[0];"
              "fetch(api('/api/state?since=' + seq)).then((r) => r.json()).then((state) => {"
              "  if (newer) state.history.unshift({id: 'newer', label: 'newer', started: state.now - 5,"
              "    finished: state.now, counts: {}, comics: [{name: 'Other', state: 'ok', gained: 1, elapsed: 5}]});"
              "  renderState(state);"
              "  done([...document.querySelectorAll('#history details')].map((d) => [d.dataset.job, d.open]));"
              "})")
    same = browser.execute_async_script(redraw, False)
    assert [opened for _, opened in same] == [True], same
    moved = browser.execute_async_script(redraw, True)
    assert [opened for _, opened in moved] == [False, True], "the newer run arrives shut: {0}".format(moved)


@pytest.mark.browser
@pytest.mark.slow
def test_the_page_shows_running_jobs_without_console_errors(page, site, browser):
    #something to show: two slow comics being added while a group waits behind them
    page.call("/api/add", {"rows": [{"folder": "Slow2", "url": site + "/slow/1"},
                                    {"folder": "Slow3", "url": site + "/slow/1"}]})
    page.call("/api/update", {"names": ["Uncompressed/Group/*"]})
    #until a comic is really being scraped and the update is waiting behind it, which is what is shown
    wait_until(lambda: (page.call("/api/state")[1].get("current") or {}).get("comics")
               and page.call("/api/state")[1].get("waiting"), why="the jobs never got going")
    try:
        browser.set_window_size(1400, 1000)
        open_page(browser, page.base.replace("http://", "http://me:{0}@".format(PASSWORD)) + "/")
        #the page polls for the state once a second, so two of those have drawn the jobs
        time.sleep(2)
        browser.set_window_size(420, 1400)
        time.sleep(0.5)
        errors = console_errors(browser)
        assert not errors, errors
    finally:
        page.call("/api/stop", {})
        page.wait_idle(60)
