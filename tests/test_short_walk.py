#a walk the site cut off part way leaves a record of which page is which that stops hundreds of pages short
#of the comic. a line's place in it is its page number, so a scrape adding its pages after the walk's last
#would number every one of them wrong - and, its last line then being the newest page, the record would
#look finished. a scrape adds nothing to such a record, and working the chapters out carries the walk on.
#a run that died fetching a page leaves a record rightly ending at the page before, which is carried on.
import argparse
import json
import os

from comiclib.chapters.index import KeptIndex, reaches_newest
from comiclib.web.views import walk_needed
from conftest import write_index, write_meta

SITE = "https://example.com"


def line(n):
    return {"n": n, "url": "{0}/comic/{1}".format(SITE, n), "src": "{0}/img/{1}.png".format(SITE, n),
            "file": "{0}.png".format(n), "title": "Page {0}".format(n), "bytes": 100 + n}


def comic_with(library, chapters, walked, newest):
    #a comic whose record runs to page `walked`, having saved pages up to `newest`
    folder = library / "Uncompressed" / "Long"
    folder.mkdir(parents=True)
    path = chapters.index_path(str(folder), str(library), None)
    write_index(path, [line(n) for n in range(1, walked + 1)])
    write_meta(folder, {"schema": 2, "settings": {"url": "{0}/comic/{1}".format(SITE, newest)},
                        "history": {"index_cache": os.path.basename(path)},
                        #saved as the site's image, with a second extension, as an older scrape named it
                        "state": {"last_image_url": "{0}/img/{1}.png".format(SITE, newest),
                                  "last_image_file": "{0}.png.png".format(newest)}})
    return folder, path


def scrape_args(start):
    return argparse.Namespace(URL=start, increment=1, keep_index=None)


def test_a_record_holding_the_newest_page_reaches_it():
    lines = [line(n) for n in range(1, 11)]
    assert reaches_newest(lines, {"last_image_url": SITE + "/img/10.png"}) is True
    #matched by name too, however many extensions an older scrape gave it
    assert reaches_newest(lines, {"last_image_file": "10.png.png"}) is True
    assert reaches_newest(lines, {"last_image_url": SITE + "/img/400.png"}) is False
    #nothing to go on either way
    assert reaches_newest(lines, {}) is None
    assert reaches_newest([], {"last_image_url": SITE + "/img/10.png"}) is None


def test_a_scrape_adds_nothing_to_a_record_that_stops_short(library, chapters, capsys):
    folder, path = comic_with(library, chapters, 40, 400)
    kept = KeptIndex()
    kept.open(str(folder), scrape_args("{0}/comic/400".format(SITE)))
    assert "stops at page 40" in capsys.readouterr().out
    kept.add("{0}/comic/401".format(SITE), SITE + "/img/401.png", "401.png", 501, "Page 401")
    with open(path, encoding="utf-8") as f:
        held = [json.loads(text) for text in f if text.strip()]
    assert len(held) == 40, "page 401 should not have been written in as page 41"
    #nor anything else this run saves
    assert kept.file is None


def test_a_scrape_carries_on_a_record_that_ends_where_the_last_run_died(library, chapters):
    #the last run saved page 10 and died fetching page 11; this run starts at 11
    folder, path = comic_with(library, chapters, 10, 10)
    kept = KeptIndex()
    kept.open(str(folder), scrape_args("{0}/comic/11".format(SITE)))
    kept.add("{0}/comic/11".format(SITE), SITE + "/img/11.png", "11.png", 111, "Page 11")
    with open(path, encoding="utf-8") as f:
        held = [json.loads(text) for text in f if text.strip()]
    assert [one["n"] for one in held] == list(range(1, 12)), held[-2:]


def test_a_record_listed_ahead_of_the_files_is_not_added_to_twice(library, chapters):
    #listed from the site to page 20 while only 10 pages are saved, and the site puts a different query on
    #its images every visit. the resumed page, and the pages after it the record already lists, are not
    #new pages; the first page past the record is
    folder, path = comic_with(library, chapters, 20, 10)
    kept = KeptIndex()
    kept.open(str(folder), scrape_args("{0}/comic/10".format(SITE)))
    kept.add("{0}/comic/10".format(SITE), SITE + "/img/10.png?v=123", "0010_10.png", 110, "Page 10")
    kept.add("{0}/comic/11/".format(SITE), SITE + "/img/11.png?x123", "0011_11.png", 111, "Page 11")
    kept.add("{0}/comic/21".format(SITE), SITE + "/img/21.png?x5", "0021_21.png", 121, "Page 21")
    with open(path, encoding="utf-8") as f:
        held = [json.loads(text) for text in f if text.strip()]
    assert [one["n"] for one in held] == list(range(1, 22))
    assert held[-1]["file"] == "0021_21.png"


def test_a_listed_page_saved_as_another_image_puts_its_line_right(library, chapters):
    #listed from the site, which named the post's thumbnail; the page itself shows the full strip, saved
    #under that page's number. one page, so its line is corrected rather than a second added after the end
    folder, path = comic_with(library, chapters, 20, 9)
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(text) for text in f if text.strip()]
    lines[9].update(src=SITE + "/img/10-thumbnail.png", file="10-thumbnail.png", bytes=7)
    write_index(path, lines)
    kept = KeptIndex()
    kept.open(str(folder), scrape_args("{0}/comic/9".format(SITE)))
    kept.add("{0}/comic/10".format(SITE), SITE + "/img/10-full.png?x5", "0010_10-full.png", 1100, "Page 10")
    with open(path, encoding="utf-8") as f:
        held = [json.loads(text) for text in f if text.strip()]
    assert len(held) == 20
    assert held[9]["file"] == "0010_10-full.png" and held[9]["bytes"] == 1100 and held[9]["n"] == 10
    #and the page after it is still the next line, not one further out
    kept.add("{0}/comic/11".format(SITE), SITE + "/img/11.png", "0011_11.png", 111, "Page 11")
    with open(path, encoding="utf-8") as f:
        assert len([text for text in f if text.strip()]) == 20


class Setup:
    #the little of update_comics that walk_needed asks of it
    @staticmethod
    def config_folder():
        from comiclib.paths import config_folder
        return config_folder()


class Held:
    def __init__(self, folder):
        with open(str(folder / "mirror_metadata.json"), encoding="utf-8") as f:
            self.metadata = json.load(f)


def test_working_out_chapters_carries_on_a_walk_that_stopped_short(library, chapters):
    folder, _ = comic_with(library, chapters, 40, 400)
    assert walk_needed(None, Setup, Held(folder)) == "carry on"


def test_working_out_chapters_leaves_a_finished_walk_alone(library, chapters):
    folder, _ = comic_with(library, chapters, 400, 400)
    assert walk_needed(None, Setup, Held(folder)) is None


def test_a_record_of_one_page_is_a_walk_that_never_happened(library, chapters):
    folder, _ = comic_with(library, chapters, 1, 1)
    assert walk_needed(None, Setup, Held(folder)) == "start"


def primed_as(folder, first_url, first_number=1):
    with open(str(folder / "mirror_metadata.json"), encoding="utf-8") as f:
        metadata = json.load(f)
    metadata["history"].update(first_page_url=first_url, first_page_number=first_number)
    write_meta(folder, metadata)


def test_a_primed_comics_one_page_record_needs_no_walk(library, chapters):
    #primed: page 1 saved, its line recorded, and the update that fetches the rest adds to it
    folder, _ = comic_with(library, chapters, 1, 1)
    primed_as(folder, "{0}/comic/1".format(SITE))
    assert walk_needed(None, Setup, Held(folder)) is None


def test_a_one_page_record_of_some_other_page_still_needs_a_walk(library, chapters):
    #a walk begun on the newest page writes that page down as its only line: not the comic's first page
    folder, _ = comic_with(library, chapters, 1, 1)
    primed_as(folder, "{0}/comic/0".format(SITE))
    assert walk_needed(None, Setup, Held(folder)) == "start"
    #nor is a comic recorded as begun part way in, whatever its one line says
    primed_as(folder, "{0}/comic/1".format(SITE), first_number=40)
    assert walk_needed(None, Setup, Held(folder)) == "start"
