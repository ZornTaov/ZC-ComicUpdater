#plugins on the web page: the list of them, a plugin's own dialog served and nothing else of it, comics
#added and edited with a plugin's settings, and the page itself - the Scraper picker, a plugin's form drawn
#from its fields or by its own dialog.js, and the editor showing a plugin comic only what it has. the
#plugin is the example one, whose program draws a made-up series, so nothing reaches the internet.
import os

import pytest

from conftest import console_errors, open_page, read_meta, wait_until
from test_plugins import URL, install


def shelf(library):
    folder = library / "CBZs" / "MyComic"
    return sorted(os.listdir(str(folder))) if folder.is_dir() else []


def added(page, library, **body):
    code, answer = page.call("/api/add", dict({"scraper": "example", "rows": [{"folder": "MyComic", "url": URL}],
                                               "plugin": {"chapters": 2}}, **body))
    assert code == 200, answer
    assert page.wait_idle(120), "the add never finished"
    return library / "Uncompressed" / "MyComic"


# ---------------- the api ----------------
def test_the_plugins_there_are_are_listed_with_what_is_wrong_with_any(library, config, web):
    install(config)
    broken = config / "plugins" / "broken"
    broken.mkdir()
    (broken / "plugin.json").write_text('{"output": "zips"}', encoding="utf-8")
    code, answer = web().call("/api/plugins")
    assert code == 200
    assert [plugin["name"] for plugin in answer["plugins"]] == ["example"]
    assert answer["plugins"][0]["dialog"] is True and answer["plugins"][0]["style"] is False
    assert [field["key"] for field in answer["plugins"][0]["fields"]] == ["url", "chapters", "pages"]
    assert len(answer["problems"]) == 1 and "has to be one of" in answer["problems"][0]


@pytest.mark.parametrize("address", [
    "/plugins/example/plugin.py", "/plugins/example/plugin.json", "/plugins/example/tool/fake_scraper.py",
    "/plugins/example/..%2F..%2FComicScraper.json", "/plugins/..%2Fexample/dialog.js", "/plugins/example/C:%2Fx.js",
    "/plugins/missing/dialog.js",
])
def test_nothing_of_a_plugin_is_served_but_its_dialog(library, config, web, address):
    install(config)
    (config / "ComicScraper.json").write_text("{}", encoding="utf-8")
    page = web()
    code, answer = page.call("/plugins/example/dialog.js")
    assert code == 200 and b'pluginForms["example"]' in answer
    assert page.call(address)[0] == 404


def test_a_comic_is_added_with_a_plugin_and_scraped_by_it(library, config, web):
    install(config)
    page = web()
    code, answer = page.call("/api/add", {"scraper": "example", "rows": [{"folder": "MyComic", "url": "nope"}]})
    assert code == 400 and "needs one http(s) address" in answer["error"]
    code, answer = page.call("/api/add", {"scraper": "example", "rows": [{"folder": "MyComic", "url": URL,
                                                                          "chapters": URL}]})
    assert code == 400 and "has its chapters from it" in answer["error"]
    code, answer = page.call("/api/add", {"scraper": "example", "rows": [{"folder": "MyComic", "url": URL}],
                                          "plugin": {"chapters": "lots"}})
    assert code == 400 and "Chapters it has must be a whole number" in answer["error"]

    comic = added(page, library)
    meta = read_meta(comic)
    assert meta["settings"]["scraper"] == "example" and meta["settings"]["plugin"] == {"chapters": 2, "pages": 2}
    assert shelf(library) == ["MyComic - c001 - Chapter 1.cbz", "MyComic - c002 - Chapter 2.cbz"]
    row = next(row for row in page.call("/api/comics")[1] if row["name"] == "Uncompressed/MyComic")
    assert (row["scraper"], row["url"], row["pages"]) == ("example", URL, 4)


def test_a_plugin_comics_settings_are_its_plugins(library, config, web):
    install(config)
    page = web()
    comic = added(page, library)
    code, detail = page.call("/api/comic?name=Uncompressed/MyComic")
    assert code == 200 and detail["plugin"]["name"] == "example"
    code, answer = page.call("/api/settings", {"name": "Uncompressed/MyComic", "updated": detail["updated"],
                                               "settings": {"plugin": {"chapters": "x"}}})
    assert code == 400 and "must be a whole number" in answer["error"]
    code, answer = page.call("/api/settings", {"name": "Uncompressed/MyComic", "updated": detail["updated"],
                                               "settings": {"plugin": {"chapters": "4", "url": URL + "2"},
                                                            "waittime": 9, "ended": True}})
    assert code == 200, answer
    assert set(answer["changed"]) == {"plugin.chapters", "url", "ended"}, "waittime is the built-in scraper's"
    settings = read_meta(comic)["settings"]
    assert settings["plugin"] == {"chapters": 4, "pages": 2} and settings["url"] == URL + "2"
    assert "waittime" not in settings


# ---------------- the page ----------------
def visible(browser, element_id):
    return browser.execute_script(
        "const e = document.getElementById(arguments[0]); return !!e && e.getClientRects().length > 0", element_id)


@pytest.mark.browser
@pytest.mark.slow
def test_a_plugin_list_that_could_not_be_had_is_asked_for_again(library, config, web, browser):
    #the list is asked for once as the page opens. a request that failed left it empty, and the picker
    #hidden, until the page was reloaded - so the page is made to fail it, and must ask again
    install(config)
    page = web()
    open_page(browser, page.base + "/")
    wait_until(lambda: visible(browser, "add-scraper-row"), why="the picker never showed")
    browser.execute_script("""
      const real = window.fetch;
      let refused = 0;
      window.fetch = (address, ...rest) => {
        if (String(address).includes("/api/plugins") && refused < 2) {
          refused++;
          return Promise.resolve(new Response("busy", {status: 503}));
        }
        return real(address, ...rest);
      };
      pluginList = [];
      showScrapers();
      loadPlugins(100);
    """)
    assert not visible(browser, "add-scraper-row"), "the picker should hide while there is no list"
    wait_until(lambda: visible(browser, "add-scraper-row"), limit=15, why="the list was never asked for again")


@pytest.mark.browser
@pytest.mark.slow
def test_the_picker_is_hidden_without_plugins_and_built_in_sends_what_it_always_did(library, config, web, browser):
    page = web()
    open_page(browser, page.base + "/")
    wait_until(lambda: browser.execute_script("return document.getElementById('add-scraper').options.length === 1"))
    assert not visible(browser, "add-scraper-row"), "a library with no plugins sees the page as it was"
    #what the add button sends, caught before it goes, with the picker left on Built in
    browser.execute_script("""
      window.sent = null;
      const real = window.fetch;
      window.fetch = (url, options) => { if (String(url).endsWith('/api/add')) { window.sent = JSON.parse(options.body);
        return Promise.resolve(new Response('{"error": "caught"}', {status: 400})); } return real(url, options); };
      document.querySelector('[data-add-field="folder"]').value = 'Old';
      document.querySelector('[data-add-field="folder"]').dispatchEvent(new Event('input', {bubbles: true}));
      document.getElementById('add').click();""")
    sent = wait_until(lambda: browser.execute_script("return window.sent"))
    assert sorted(sent) == ["cbz", "direction_check", "every", "increment", "javascript", "prefix", "prime", "rows",
                            "waittime"]
    assert sent["rows"] == [{"folder": "Old", "cbz": "", "url": "", "chapters": ""}]


@pytest.mark.browser
@pytest.mark.slow
@pytest.mark.parametrize("own_dialog", [True, False])
def test_a_comic_added_on_the_page_with_a_plugin(library, config, web, browser, own_dialog):
    folder = install(config)
    if not own_dialog:
        os.remove(os.path.join(folder, "dialog.js"))
    page = web()
    open_page(browser, page.base + "/")
    wait_until(lambda: visible(browser, "add-scraper-row"), why="the picker never showed")
    browser.execute_script("const p = document.getElementById('add-scraper'); p.value = 'example';"
                           "p.dispatchEvent(new Event('change'))")
    #drawn by the plugin's own dialog.js, or from its fields
    form = "[data-example-form]" if own_dialog else "[data-plugin-field='chapters']"
    wait_until(lambda: browser.execute_script("return document.querySelector(arguments[0])", form),
               why="the plugin's form never drew")
    assert not visible(browser, "prime"), "the built-in scraper's options are put away"
    assert browser.execute_script("return getComputedStyle(document.querySelector("
                                  "'[data-add-field=\"chapters\"]')).visibility") == "hidden"
    key = "data-key" if own_dialog else "data-plugin-field"
    browser.execute_script("""
      const set = (sel, value) => { const e = document.querySelector(sel); e.value = value;
        e.dispatchEvent(new Event('input', {bubbles: true})); };
      set('[data-add-field="folder"]', 'MyComic');
      set('[data-add-field="url"]', arguments[0]);
      set('#add-plugin [' + arguments[1] + '="chapters"]', '3');
      document.getElementById('add').click();""", URL, key)
    wait_until(lambda: "Queued" in browser.execute_script("return document.getElementById('add-msg').textContent"),
               why=browser.execute_script("return document.getElementById('add-msg').textContent"))
    assert page.wait_idle(120), "the add never finished"
    meta = read_meta(library / "Uncompressed" / "MyComic")
    assert meta["settings"]["plugin"]["chapters"] == 3 and meta["settings"]["url"] == URL
    assert len(meta["chapters"]["list"]) == 3
    assert not console_errors(browser), console_errors(browser)


@pytest.mark.browser
@pytest.mark.slow
def test_the_editor_shows_a_plugin_comic_its_plugins_settings_and_saves_them(library, config, web, browser):
    folder = install(config)
    os.remove(os.path.join(folder, "dialog.js"))
    page = web()
    comic = added(page, library)
    open_page(browser, page.base + "/")
    wait_until(lambda: browser.execute_script(
        "return document.querySelector('[data-edit=\"Uncompressed/MyComic\"]')"), why="the comic never listed")
    assert browser.execute_script("return document.querySelector('td.name .scraper').textContent") == "example"
    browser.execute_script("document.querySelector('[data-edit=\"Uncompressed/MyComic\"]').click()")
    wait_until(lambda: browser.execute_script("return document.querySelector('#e-plugin [data-plugin-field=\"url\"]')"),
               why="the plugin's settings never drew")
    for put_away in ("e-url", "e-increment", "e-chapters", "edit-chapterize", "e-prefix"):
        assert not visible(browser, put_away), put_away + " is the built-in scraper's"
    assert visible(browser, "e-cbz") and visible(browser, "e-ended")
    assert browser.execute_script("return document.querySelector('#e-plugin [data-plugin-field=\"chapters\"]').value") == "2"
    browser.execute_script("document.querySelector('#e-plugin [data-plugin-field=\"chapters\"]').value = '5';"
                           "document.getElementById('edit-save').click()")
    wait_until(lambda: "Saved" in browser.execute_script("return document.getElementById('edit-msg').textContent"),
               why=browser.execute_script("return document.getElementById('edit-msg').textContent"))
    assert read_meta(comic)["settings"]["plugin"]["chapters"] == 5
    assert not console_errors(browser), console_errors(browser)
