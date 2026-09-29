#the settings file in the config folder: read at start, beaten by the command line, saved from the page
#and picked up by the next job without a restart, and survived when it is damaged.
import json

import pytest

from conftest import PNG, Site, pages_in, read_meta

PAGES = 3


class Short(Site):
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
            return
        number = self.path.rsplit("/", 1)[-1]
        if not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        link = '<a href="/c/{0}">Next</a>'.format(number + 1) if number < PAGES else ""
        self.send('<html><body><div id="wrap">{1}<img id="comic-image" src="/img/{0:04d}.png">'
                  '</div></body></html>'.format(number, link))


@pytest.fixture
def site(serve):
    return serve(Short)


@pytest.fixture
def page(web, config):
    #a settings file that renames both library folders and sets a couple of run options, and a --jobs on
    #the command line that has to beat the file's
    with open(config / "ComicScraper.json", "w", encoding="utf-8") as f:
        json.dump({"pages_folder": "Pages", "cbz_folder": "Archives", "jobs": 3, "timeout": 900,
                   "progress": 0, "add_defaults": {"prefix": True, "increment": 7}}, f, indent=2)
    return web(extra=("--jobs", "2"))


def saved_settings(config):
    with open(config / "ComicScraper.json", encoding="utf-8") as f:
        return json.load(f)


def test_the_settings_file_is_read_and_the_command_line_still_wins(page, config):
    code, cfg = page.call("/api/config")
    assert code == 200 and cfg["path"] == str(config / "ComicScraper.json"), cfg.get("path")
    assert cfg["settings"]["pages_folder"] == "Pages" and cfg["settings"]["timeout"] == 900, cfg["settings"]
    #what is left out falls back to a default
    assert cfg["settings"]["max_depth"] == 5, cfg["settings"]
    _, state = page.call("/api/state")
    assert state["jobs_at_once"] == 2, "--jobs 2 should beat the file's 3"
    #the page knows which settings the command line fixed, so it can say why changing them does nothing
    assert "jobs" in cfg["from_command_line"], cfg["from_command_line"]


@pytest.mark.browser
@pytest.mark.slow
def test_added_comics_go_under_the_configured_folders(page, site, library):
    code, answer = page.call("/api/add", {"rows": [
        {"folder": "ComicName", "url": site + "/c/1"},
        {"folder": "ComicSeries/ComicA", "url": site + "/c/1"},
        {"folder": "ComicSeries/ComicB", "cbz": "ComicSeries/B-custom.cbz", "url": site + "/c/1"}]})
    assert code == 200, answer
    assert page.wait_idle(180), "the add never finished"
    pages = library / "Pages"
    assert len(pages_in(pages / "ComicName")) == PAGES, list(pages.iterdir())
    assert len(pages_in(pages / "ComicSeries" / "ComicA")) == PAGES, list(pages.iterdir())
    #numbered from 7, as the settings file's add defaults asked
    assert pages_in(pages / "ComicName")[0].startswith("0007_"), pages_in(pages / "ComicName")
    archives = library / "Archives"
    #a comic with no folder of its own gets one; one already in a group sits beside its siblings; and an
    #archive path given outright is used as written
    assert (archives / "ComicName" / "ComicName.cbz").is_file(), list(archives.iterdir())
    assert (archives / "ComicSeries" / "ComicA.cbz").is_file(), list((archives / "ComicSeries").iterdir())
    assert (archives / "ComicSeries" / "B-custom.cbz").is_file(), list((archives / "ComicSeries").iterdir())
    assert read_meta(pages / "ComicName")["settings"]["prefix"] is True

    #typing the library's own folder names in as well does not double them
    assert page.call("/api/add", {"rows": [{"folder": "Pages/Typed", "cbz": "Archives/Typed/Typed.cbz",
                                            "url": site + "/c/1"}]})[0] == 200
    assert page.wait_idle(180), "the add never finished"
    assert (pages / "Typed").is_dir() and not (pages / "Pages").exists(), list(pages.iterdir())


@pytest.mark.browser
@pytest.mark.slow
def test_settings_saved_from_the_page_reach_the_next_job(page, site, library, config):
    _, cfg = page.call("/api/config")
    code, answer = page.call("/api/config", {"settings": dict(cfg["settings"], timeout=1200, max_depth=4,
                                                              schedule="")})
    assert code == 200 and answer["settings"]["timeout"] == 1200, answer
    saved = saved_settings(config)
    assert saved["timeout"] == 1200 and saved["pages_folder"] == "Pages", saved

    assert page.call("/api/config", {"settings": {"schedule": "half past three"}})[0] == 400
    assert page.call("/api/config", {"settings": {"jobs": "lots"}})[0] == 400
    assert page.call("/api/config", {"settings": {"pages_folder": "../elsewhere"}})[0] == 400
    assert saved_settings(config)["timeout"] == 1200, "a refused save changed the file"

    #rename the pages folder while it is running: the next job has to use the new name
    page.call("/api/config", {"settings": dict(cfg["settings"], pages_folder="Elsewhere")})
    page.call("/api/add", {"rows": [{"folder": "Later", "url": site + "/c/1"}]})
    assert page.wait_idle(180), "the add never finished"
    assert (library / "Elsewhere" / "Later").is_dir(), sorted(p.name for p in library.iterdir())


@pytest.mark.browser
@pytest.mark.slow
def test_a_damaged_settings_file_falls_back_to_the_defaults(page, site, library, config):
    (config / "ComicScraper.json").write_text("{ nope", encoding="utf-8")
    page.call("/api/add", {"rows": [{"folder": "Fallback", "url": site + "/c/1"}]})
    assert page.wait_idle(180), "the add never finished"
    assert (library / "Uncompressed" / "Fallback").is_dir(), sorted(p.name for p in library.iterdir())
    assert "WARNING: ignoring" in page.said(), page.log[-3:]
