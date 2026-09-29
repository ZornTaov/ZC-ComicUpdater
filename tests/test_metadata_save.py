#what a run writes into mirror_metadata.json: schema 2, with the settings block the only thing anyone edits,
#and an older schema 1 file read and upgraded without losing what only it knew.
import argparse
import json

import pytest


class StubDriver(object):
    current_url = "https://example.com/comic/44/"

    def quit(self):
        pass


def fresh_args():
    return argparse.Namespace(
        URL="https://example.com/comic/43/", output="Uncompressed/TestComic",
        cbz_path="CBZs/TestComic.cbz", prefix=True, enable_javascript=False, firefox=False,
        waittime=0, cbz=True, increment=43, headless=True, chrome=False, verbose=False,
        element_find_manual=False, element_find_next_manual=False, direction_check=True,
        multi_page=True)


@pytest.fixture
def saving(library, mirror, monkeypatch):
    #a comic of three pages, and mirror_base left as a run that saved two of them would leave it: both
    #new to the folder, since a run that adds nothing writes nothing down, and already following the next
    #link to the page after, which is where a later run carries on
    comic = library / "Uncompressed" / "TestComic"
    comic.mkdir()
    for n in range(1, 4):
        (comic / "{0:04d}_page.jpg".format(n)).write_bytes(b"x")
    mirror.scrape_state.update({
        "pages_saved": 2, "fresh_pages": 2, "first_page_url": "https://example.com/comic/1/",
        "first_increment": 1, "last_page_url": "https://example.com/comic/43/", "last_increment": 43,
        "last_image_src": "https://example.com/img/43.png", "last_image_file": "0043_43.png",
        "walked_to": "https://example.com/comic/44/",
    })
    mirror.image_xpath = '//*[@id="comic"]/img'
    mirror.next_xpath = '//*[@rel="next"]'
    mirror.stop_reason = "no next button"
    monkeypatch.chdir(library)
    return comic


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_a_fresh_comic_gets_a_schema_2_file(saving, mirror):
    meta = load(mirror.metadata_save(StubDriver(), fresh_args(), completed=True, exit_code=0))
    assert meta.get("schema") == 2, meta.get("schema")
    assert set(meta) == {"schema", "generator", "generator_version", "created", "updated",
                         "settings", "state", "history"}, sorted(meta)
    s = meta["settings"]
    assert s["prefix"] is True, s
    assert len(s) == 12, "every setting should always be written: {0}".format(sorted(s))
    #the page the run walked to meaning to save it, not wherever the browser happens to be standing
    assert s["url"] == "https://example.com/comic/44/", "resume url not advanced to the page walked to"
    assert s["increment"] == 44, "increment not advanced past the saved page: {0}".format(s["increment"])
    assert s["cbz_path"] == "CBZs/TestComic.cbz", s["cbz_path"]
    assert "resume_argv" not in json.dumps(meta)
    assert "resume_command_line" not in json.dumps(meta)
    #argv is the record of what a run was told; the rendered command and option dump said it twice more
    first = meta["history"]["runs"][0]
    assert "argv" in first and "command_line" not in first and "options" not in first, first.keys()
    assert meta["state"]["page_count"] == 3, meta["state"]["page_count"]
    assert meta["state"]["image_xpath"] == '//*[@id="comic"]/img'


def test_a_schema_1_file_is_upgraded_keeping_what_only_it_knows(saving, mirror):
    old = {
        "generator": "adopt_comic.py", "created": "2020-01-01T00:00:00Z",
        "source_url": "https://example.com/comic/1/",
        "first_page_url": "https://example.com/comic/1/", "first_page_number": 1,
        "image_xpath": "//old/xpath", "next_xpath": "//old/next",
        "ended": True, "adopted": True,
        "adopted_from": {"path": "somewhere", "numbering": "prefixed"},
        "runs": [{"run_id": "older", "argv": ["-o", "x"], "command_line": "python ...",
                  "options": {"prefix": True}}],
    }
    with open(saving / "mirror_metadata.json", "w", encoding="utf-8") as f:
        json.dump(old, f)
    #this run discovered nothing, so the old values must survive
    mirror.image_xpath = None
    mirror.next_xpath = None
    meta = load(mirror.metadata_save(StubDriver(), fresh_args(), completed=False, exit_code=0))
    assert meta.get("schema") == 2
    assert meta["created"] == "2020-01-01T00:00:00Z", meta["created"]
    assert meta["history"]["first_page_url"] == "https://example.com/comic/1/"
    assert meta["history"]["first_page_number"] == 1
    #a comic marked finished by hand stays finished through a run made directly
    assert meta["settings"]["ended"] is True, meta["settings"]["ended"]
    assert meta["state"]["image_xpath"] == "//old/xpath", meta["state"]["image_xpath"]
    assert meta["history"]["adopted"] is True
    assert "adopted_from" in meta["history"]
    assert len(meta["history"]["runs"]) == 2, "the old run should be kept and the new one appended"
