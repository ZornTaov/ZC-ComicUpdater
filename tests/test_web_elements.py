#the element paths as the web page shows and saves them: the lists mirror_base ships with, a check of a
#page none of them can read and the paths it suggests, what a save refuses, and a saved file being what
#mirror_base then scrapes with - or, when it is damaged, ignores.
import json
import time

import pytest

from conftest import PNG_240, Site, checked, console_errors, open_page, pages_in, run

PAGES = 5
ADDED_IMAGE = '//img[@class="strip-art"]'
ADDED_NEXT = '//*[@class="onwards"]'


class Unknown(Site):
    #nothing here matches any shipped path: the image is <img class="strip-art">, the next link is
    #<a class="onwards">, and the image also sits inside a link to the PREVIOUS page
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG_240, "image/png")
            return
        number = self.path.rsplit("/", 1)[-1]
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        link = '<a class="onwards" href="/p/{0}">Onwards</a>'.format(number + 1) if number < PAGES else ""
        self.send('<html><head><title>Odd Comic {0}</title></head><body><div class="wrap">'
                  '<a href="/p/{2}"><img class="strip-art" width="240" height="240" src="/img/{0:04d}.png"></a>'
                  '{1}</div></body></html>'.format(number, link, max(number - 1, 1)))


def shipped_from_source():
    #the two lists as comiclib ships them, each xpath with its note, read from the module itself so the
    #test follows the lists as they change rather than a copy of them
    from comiclib.elements import shipped
    lists = {kind: [entry["xpath"] for entry in entries] for kind, entries in shipped.items()}
    notes = {kind: [entry.get("note", "") for entry in entries] for kind, entries in shipped.items()}
    return lists, notes


@pytest.fixture
def site(serve):
    return serve(Unknown)


def last_check(page):
    state = page.wait_idle(180)
    assert state, "the check never finished"
    return state["history"][0]["check"]


@pytest.mark.browser
@pytest.mark.slow
def test_a_comic_the_shipped_paths_do_not_know_fails_as_it_should(site, library):
    done = run("mirror_base.py", "-o", library / "Uncompressed" / "Odd", "--no-cbz", site + "/p/1", cwd=library)
    assert done.returncode == 3, done.stdout[-200:]


def test_the_shipped_lists_as_the_page_shows_them(web, config):
    lists, notes = shipped_from_source()
    code, data = web().call("/api/elements")
    assert code == 200, data
    for kind in ("image", "next"):
        assert data[kind], "the {0} list is empty".format(kind)
        assert all(entry.get("xpath") for entry in data[kind]), data[kind]
        #in the order the script tries them, with the comment beside each one as its note
        assert [entry["xpath"] for entry in data[kind]] == lists[kind]
        assert [entry["note"] for entry in data[kind]] == notes[kind]
        assert all(entry["shipped"] and entry["enabled"] for entry in data[kind])
    assert data["saved"] is False
    assert data["path"] == str(config / "element_paths.json"), data["path"]


@pytest.mark.browser
@pytest.mark.slow
def test_a_check_of_a_page_nothing_reads_suggests_paths(web, site):
    page = web()
    code, answer = page.call("/api/check", {"url": site + "/p/2"})
    assert code == 200, answer
    assert page.call("/api/check", {"url": "nope"})[0] == 400
    found = last_check(page)
    assert found["image"] == [] and found["next"] == [], found
    guesses = found.get("suggestions", {})
    image_guess = [g["suggested"] for g in guesses.get("image", []) if g.get("suggested")]
    next_guess = [g["suggested"] for g in guesses.get("next", []) if g.get("suggested")]
    assert any("strip-art" in guess for guess in image_guess), image_guess
    assert any("onwards" in guess for guess in next_guess), next_guess
    assert found.get("title") == "Odd Comic 2", found.get("title")


def test_a_bad_save_is_refused_and_writes_nothing(web, config):
    page = web()
    _, data = page.call("/api/elements")
    assert page.call("/api/elements", {"image": [{"xpath": "strip-art"}], "next": data["next"]})[0] == 400, \
        "an xpath that is not one should be refused"
    assert page.call("/api/elements", {"image": [], "next": data["next"]})[0] == 400, \
        "emptying a list should be refused"
    assert page.call("/api/elements", {"image": [{"xpath": "//a"}, {"xpath": "//a"}],
                                       "next": data["next"]})[0] == 400, "the same path twice should be refused"
    assert not (config / "element_paths.json").exists()


def save_added_paths(page):
    #the two paths the check suggests, put at the top, and one shipped path turned off
    _, data = page.call("/api/elements")
    turned_off = data["next"][0]["xpath"]
    image = [{"xpath": ADDED_IMAGE, "note": "Odd Comic", "enabled": True}] + data["image"]
    nexts = [{"xpath": ADDED_NEXT, "note": "Odd Comic", "enabled": True}] + data["next"]
    nexts = [dict(e, enabled=False) if e["xpath"] == turned_off else e for e in nexts]
    code, answer = page.call("/api/elements", {"image": image, "next": nexts})
    assert code == 200 and answer["saved"], answer
    return data, turned_off


@pytest.mark.browser
@pytest.mark.slow
def test_saved_paths_are_kept_in_order_and_scraped_with(web, site, library, config):
    page = web()
    shipped, turned_off = save_added_paths(page)
    with open(config / "element_paths.json", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["image"][0]["xpath"] == ADDED_IMAGE and saved["next"][0]["note"] == "Odd Comic", saved["image"][:1]
    assert any(e["xpath"] == turned_off and e["enabled"] is False for e in saved["next"]), \
        "the turned-off path should be kept, marked off"

    _, again = page.call("/api/elements")
    assert again["saved"] and again["image"][0]["note"] == "Odd Comic" and again["image"][0]["shipped"] is False, \
        again["image"][:1]
    #the saved order is kept, and every shipped path still turns up behind the added one
    assert [e["xpath"] for e in again["image"]] == [ADDED_IMAGE] + [e["xpath"] for e in shipped["image"]]
    assert [e["xpath"] for e in again["next"] if not e["enabled"]] == [turned_off]

    code, answer = page.call("/api/add", {"rows": [{"folder": "Odd2", "url": site + "/p/1"}]})
    assert code == 200, answer
    assert page.wait_idle(180), "the scrape never finished"
    assert pages_in(library / "Uncompressed" / "Odd2") == ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)]

    page.call("/api/check", {"url": site + "/p/2"})
    found = last_check(page)
    assert found["image"][0]["xpath"] == ADDED_IMAGE and found["next"][0]["xpath"] == ADDED_NEXT, found


@pytest.mark.browser
@pytest.mark.slow
def test_a_damaged_file_never_stops_a_scrape(web, site, library, config):
    lists, _ = shipped_from_source()
    (config / "element_paths.json").write_text("{ this is not json", encoding="utf-8")
    done = run("mirror_base.py", "--check", site + "/p/2", cwd=library)
    assert "WARNING: ignoring" in done.stdout and done.returncode == 0, done.stdout[-300:]
    _, data = web().call("/api/elements")
    assert data.get("problem"), "the page should say what is wrong with the file"
    assert [e["xpath"] for e in data["image"]] == lists["image"], "the built-in list should carry on alone"


@pytest.mark.browser
@pytest.mark.slow
def test_the_elements_dialog_runs_a_check_without_console_errors(web, site, browser):
    page = web()
    save_added_paths(page)
    for width, height in ((1300, 1000), (430, 1200)):
        browser.set_window_size(width, height)
        open_page(browser, page.base + "/")
        browser.execute_script("document.getElementById('open-elements').click();"
                               "document.getElementById('check-url').value = arguments[0];", site + "/p/2")
        browser.execute_script("document.getElementById('check-go').click()")
        checked(browser)
    errors = console_errors(browser)
    assert not errors, errors


@pytest.mark.browser
@pytest.mark.slow
def test_the_elements_dialog_keeps_its_buttons_on_a_small_screen(web, site, browser):
    #the help opened and a check's answer shown make the dialog taller than a 720p screen. its body has to
    #scroll with the buttons still on screen below it: the form once grew to its content instead, and the
    #dialog cut it off at the screen's edge, Save and Close with it
    page = web()
    browser.set_window_size(1280, 720)
    open_page(browser, page.base + "/")
    browser.execute_script("document.getElementById('open-elements').click();"
                           "document.getElementById('ep-howto').open = true;"
                           "document.getElementById('check-url').value = arguments[0];"
                           "document.getElementById('check-go').click()", site + "/p/2")
    checked(browser)
    body = browser.execute_script("const b = document.querySelector('#elements .dlg-body');"
                                  "return [b.scrollHeight, b.clientHeight]")
    assert body[0] > body[1], "the dialog should have more than fits, or this tests nothing: {0}".format(body)
    for button in ("ep-save", "ep-cancel"):
        #on screen, and the thing a click there would land on
        shown = browser.execute_script(
            "const b = document.getElementById(arguments[0]), r = b.getBoundingClientRect();"
            "return r.bottom <= innerHeight && document.elementFromPoint(r.left + r.width / 2,"
            " r.top + r.height / 2) === b", button)
        assert shown, "{0} is off the bottom of the screen".format(button)
