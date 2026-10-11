#a page kept as a note of its address rather than the pictures on it - one comic drawn as a grid of separate
#animations - and the pages a folder lost fetched again from the walk's record of them. no browser and no
#network: the record is written here, and fetch is replaced.
import argparse
import json

from comiclib.chapters import pageops
from conftest import read_meta, write_index, write_meta
from test_image_path import Page, comic, scrape  # noqa: F401
from test_multipage import folder, mb, pages, save  # noqa: F401

from conftest import scrape_args

SITE = "https://example.com"


def args_for(library, **over):
    return argparse.Namespace(**dict({"root": str(library), "cache": None, "url": None, "forget": False,
                                      "dry_run": False, "missing": False, "page": None, "all": False,
                                      "as_named": False, "repack": False}, **over))


def walked(chapters, comic_folder, lines):
    path = chapters.index_path(str(comic_folder))
    write_index(path, lines)
    return path


def line(n, page, src=None, file=None):
    return {"n": n, "url": "{0}/{1}/".format(SITE, page), "src": src, "file": file, "title": "Page {0}".format(page)}


def test_a_page_of_several_pictures_kept_as_a_note_is_one_page(chapters, library):
    folder_of = library / "Uncompressed" / "MyComic"
    write_meta(folder_of, {"schema": 2, "settings": {"url": SITE + "/5/"}})
    #a page you play with further on, which the walk kept as a note under the number it had then
    path = walked(chapters, folder_of, [line(1, 1, SITE + "/a.png", "a.png"),
                                        line(2, 2, SITE + "/b1.gif", "b1.gif"), line(3, 2, SITE + "/b2.gif", "b2.gif"),
                                        line(4, 2, SITE + "/b3.gif", "b3.gif"), line(5, 3, SITE + "/c.png", "c.png"),
                                        line(6, 4, None, "0006_4.url")])
    assert chapters.note_page(str(folder_of), args_for(library, url=SITE + "/2/")) == 0
    with open(path, encoding="utf-8") as f:
        now = [json.loads(one) for one in f if one.strip()]
    assert [(one["n"], one["url"].rsplit("/", 2)[-2], one["file"]) for one in now] == \
        [(1, "1", "a.png"), (2, "2", "0002_2.url"), (3, "3", "c.png"), (4, "4", "0004_4.url")], \
        "one note, the pages after it counted on, and a later note named for its new number"
    assert read_meta(folder_of)["notes"] == [SITE + "/2/"]
    with open(str(path) + ".before-note", encoding="utf-8") as f:
        assert len(f.readlines()) == 6, "the record as it was is kept beside it"


def test_missing_pages_are_fetched_and_notes_written_and_nothing_held_is_touched(chapters, library, monkeypatch):
    folder_of = library / "Uncompressed" / "MyComic"
    write_meta(folder_of, {"schema": 2, "settings": {"url": SITE + "/4/"}})
    (folder_of / "0001_a.png").write_bytes(b"page one")
    path = walked(chapters, folder_of, [line(1, 1, SITE + "/a.png", "a.png"), line(2, 2, SITE + "/b.png", "b.png"),
                                        line(3, 3, None, "0003_3.url"), line(4, 4, SITE + "/d.png", "d.png")])
    with open(chapters.alignment_path(path), "w", encoding="utf-8") as f:
        json.dump({"comic": str(folder_of), "settled": False, "pages": [
            {"n": 1, "url": SITE + "/1/", "src": SITE + "/a.png", "file": "0001_a.png"},
            {"n": 2, "url": SITE + "/2/", "src": SITE + "/b.png", "file": None},
            {"n": 3, "url": SITE + "/3/", "src": None, "file": None},
            {"n": 4, "url": SITE + "/4/", "src": SITE + "/d.png", "file": None}]}, f)

    class Answer(object):
        headers = {}

        def __init__(self, src):
            self.content = ("picture at " + src).encode("utf-8")

    asked = []
    monkeypatch.setattr(pageops, "fetch",
                        lambda src, attempts=3, referer=None: asked.append((src, referer)) or Answer(src))
    assert chapters.refetch(str(folder_of), args_for(library, missing=True)) == 0
    held = sorted(p.name for p in folder_of.iterdir() if p.name != "mirror_metadata.json")
    assert held == ["0001_a.png", "0002_b.png", "0003_3.url", "0004_d.png"]
    assert (folder_of / "0001_a.png").read_bytes() == b"page one", "what was here is left as it is"
    assert "URL=https://example.com/3/" in (folder_of / "0003_3.url").read_text()
    assert asked[0] == (SITE + "/b.png", SITE + "/2/"), "fetched with its own page as the referrer"


def test_a_scrape_keeps_a_noted_page_as_a_note_whatever_pictures_it_holds(scrape, folder):  # noqa: F811
    from comiclib.chapters.links import same_page
    scrape.noted_pages = {same_page("https://example.com/2/")}
    page = Page(scrape)
    said, nxt = save(scrape, page.at("https://example.com/1/", comic=comic(1)), scrape_args(folder), 1)
    said, nxt = save(scrape, page.at("https://example.com/2/", comic=comic(2)), scrape_args(folder), nxt)
    assert pages(scrape, folder) == ["0001_strip_1.png", "0002_2.url"]


def test_a_notes_name_says_its_page_and_where_it_lives(chapters):
    from comiclib.standin import note_name
    assert note_name(1607, "https://example.com/1608/") == "1607_1608.url"
    assert note_name(12, "https://example.com/comic/the-game/?ref=x") == "0012_the-game.url"
    assert note_name(3, "https://example.com/") == "0003_link.url", "an address with no path of its own"
