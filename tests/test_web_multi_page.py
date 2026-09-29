#the web page's side of several pages on one address: what the check hands it, what it shows, and whether
#the setting can be changed from the page at all. a real browser, a real check, a real fake comic.
import time

import pytest

from conftest import PNG_240, Site, checked, console_errors, open_page, read_meta, wait_until, write_meta

NAME = "Uncompressed/Multi"


class Multi(Site):
    #/p/N serves three numbered pages and one unnumbered button in the one container, which is the shape
    #that has to be told apart. /js/N puts its page in with javascript, building the name out of pieces so
    #the name never appears in what the server sends - the difference a check is supposed to notice.
    def do_GET(self):
        if self.path.startswith("/img/") or self.path.startswith("/nav/"):
            self.send(PNG_240, "image/png")
            return
        if self.path.startswith("/js/"):
            self.send('<html><head><title>Built by javascript</title></head><body>'
                      '<div class="comic"></div><a rel="next" href="/js/9">Next</a>'
                      '<script>var bit = "000" + 3 + "_1"; var img = document.createElement("img");'
                      'img.width = 240; img.height = 240; img.src = "/img/" + bit + ".png";'
                      'document.querySelector(".comic").appendChild(img);</script>'
                      '</body></html>')
            return
        number = self.path.rsplit("/", 1)[-1]
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        pages = "".join('<img width="240" height="240" src="/img/{0:04d}_{1}.png">'.format(number, at)
                        for at in (1, 2, 3))
        self.send('<html><head><title>Multi Comic {0}</title></head><body>'
                  '<div class="comic">{1}<img width="240" height="240" src="/nav/next.png"></div>'
                  '<a rel="next" href="/p/{2}">Next</a>'
                  '</body></html>'.format(number, pages, number + 1))


@pytest.fixture
def site(serve):
    return serve(Multi)


@pytest.fixture
def comic(site, library):
    folder = library / "Uncompressed" / "Multi"
    folder.mkdir(parents=True)
    for at in (1, 2, 3):
        (folder / "000{0}_0002_{0}.png".format(at)).write_bytes(PNG_240)
    #written by hand rather than scraped, so the state this is about is already in it
    write_meta(folder, {
        "schema": 2, "generator": "mirror_base.py", "generator_version": "3.5",
        "created": "2026-09-01T00:00:00Z", "updated": "2026-09-01T00:00:00Z",
        "settings": {"url": site + "/p/3", "output": NAME, "cbz_path": "CBZs/Multi.cbz",
                     "increment": 4, "prefix": True, "javascript": False, "firefox": False, "waittime": 0,
                     "cbz": False, "direction_check": True, "multi_page": True, "ended": False},
        "state": {"page_count": 3, "completed": False, "image_xpath": '//*[@class="comic"]/img',
                  "next_xpath": '//*[@rel="next"]', "pages_per_url": 6,
                  "multi_page_from": site + "/p/2"},
        "history": {"first_page_url": site + "/p/1", "runs": []},
    })
    return folder


def run_check(page, url, limit=180):
    code, queued = page.call("/api/check", {"url": url})
    assert code == 200, queued
    end = time.time() + limit
    while time.time() < end:
        _, state = page.call("/api/state")
        running = [state["current"]] if state.get("current") else []
        for job in (state.get("history") or []) + running + (state.get("waiting") or []):
            if job.get("id") == queued["queued"] and job.get("check"):
                return job["check"]
        time.sleep(0.5)
    raise AssertionError("the check never finished")


@pytest.mark.browser
@pytest.mark.slow
def test_the_check_counts_the_pages_on_one_address(web, site, comic):
    found = run_check(web(), site + "/p/2")
    top = (found.get("image") or [{}])[0]
    assert top.get("xpath") == '//*[@class="comic"]/img', "the winning path is the one that finds them all"
    assert top.get("count") == 4, found.get("image")
    assert top.get("page_count") == 3, top.get("page_count")
    #the button is the one left out
    assert [one.rsplit("/", 1)[-1] for one in top.get("pages") or []] == \
        ["0002_1.png", "0002_2.png", "0002_3.png"], top.get("pages")
    assert found.get("needs_javascript") is False, "a page the server sends is not a javascript page"


@pytest.mark.browser
@pytest.mark.slow
def test_the_check_says_when_a_page_needs_javascript(web, site, comic):
    built = run_check(web(), site + "/js/3")
    #the path still matches, since the check runs with javascript on
    assert built.get("image"), built
    #and the check says javascript is what a run would be missing
    assert built.get("needs_javascript") is True, built.get("needs_javascript")


def test_the_setting_can_be_changed_from_the_page(web, comic):
    page = web()
    _, detail = page.call("/api/comic?name=" + NAME)
    assert detail.get("state", {}).get("pages_per_url") == 6, detail.get("state")
    code, saved = page.call("/api/settings", {"name": NAME, "updated": detail.get("updated"),
                                              "settings": {"multi_page": False}})
    assert code == 200, saved
    meta = read_meta(comic)
    assert meta["settings"].get("multi_page") is False, meta["settings"]
    assert any("multi_page" in (edit.get("changed") or {}) for edit in (meta["history"].get("edits") or [])), \
        "the edit should be recorded like any other: {0}".format(meta["history"].get("edits"))


def run_check_in_page(browser, url):
    browser.execute_script("document.getElementById('check-url').value = arguments[0];", url)
    browser.execute_script("document.getElementById('check-go').click()")
    return checked(browser)


@pytest.mark.browser
@pytest.mark.slow
def test_what_the_page_shows(web, site, comic, browser):
    page = web()
    browser.set_window_size(1300, 1050)
    open_page(browser, page.base + "/")
    #the elements dialog holds the check, and the path list behind it takes the counts
    browser.execute_script("document.getElementById('open-elements').click();")
    result = run_check_in_page(browser, site + "/p/2")
    assert "Several pages on one address" in result, result[:300]
    assert "4 images" in result and "3 of them pages" in result, result[:300]
    assert "0002_1.png" in result, result[:300]
    assert "needs javascript" not in result.lower(), result[:300]
    listed = browser.execute_script("return document.getElementById('ep-lists').innerText")
    assert "4 images, 3 pages" in listed, [line for line in listed.splitlines() if "images" in line]
    #and marks the one a scrape would use
    assert "used ·" in listed, [line for line in listed.splitlines() if "used" in line]

    #and the javascript warning, on the page that needs it
    result = run_check_in_page(browser, site + "/js/3")
    assert "This comic needs javascript" in result, result[:300]

    #the comic's own settings: the row about addresses, and the tick box
    browser.execute_script("document.getElementById('elements').close();")
    browser.execute_script("openEditor('{0}')".format(NAME))
    facts = wait_until(lambda: (lambda said: said if "Pages an address" in said else None)(
        browser.execute_script("return document.getElementById('edit-facts').innerText")),
        why="the editor never showed the comic's facts")
    assert "Pages an address" in facts and "up to 6" in facts, facts[:400]
    assert browser.execute_script("return document.getElementById('e-multi_page').checked") is True, \
        "the several-pages box should be ticked for a comic that reads them all"
    errors = console_errors(browser)
    assert not errors, errors
