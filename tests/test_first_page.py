#the links back to a comic's first page, which a walk of a comic whose start was never recorded follows
#before it begins: found by paths kept with the others in element_paths.json, and a walk that cannot find
#one stopping rather than numbering its pages from wherever it was pointed.
import json

import pytest

from conftest import Comic, comic_page, run

PAGES = 6


class PictureButton(Comic):
    #a site built by hand: its way back to the start is a picture of a button, with no alt, title or rel to
    #say what it is - only the picture's own name
    pages = PAGES

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < self.pages else None
        back = '<a href="/p/1"><img src="/art/comicfirst.gif"></a>'
        return comic_page("/img/{0:04d}.png".format(number), onward).replace("</body>", back + "</body>")


class NoWayBack(Comic):
    #a comic with a next link and nothing at all leading back to its start
    pages = PAGES


class OwnButton(Comic):
    #a way back that none of the shipped paths would know: a bare link with a class of the site's own
    pages = PAGES

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < self.pages else None
        back = '<a class="to-start" href="/p/1">&#9198;</a>'
        return comic_page("/img/{0:04d}.png".format(number), onward).replace("</body>", back + "</body>")


def walked(index):
    with open(str(index), encoding="utf-8") as f:
        return [json.loads(text)["url"].rsplit("/", 1)[-1] for text in f if text.strip()]


@pytest.mark.browser
def test_a_walk_finds_its_way_back_by_a_picture_named_for_the_first_page(tmp_path, serve):
    site = serve(PictureButton)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, "--index-first", site + "/p/4", cwd=tmp_path)
    assert done.returncode == 0, done.stdout[-400:]
    assert walked(index) == [str(n) for n in range(1, PAGES + 1)], "the walk starts from page 1"


@pytest.mark.browser
def test_a_walk_with_no_way_back_stops_and_writes_nothing(tmp_path, serve):
    site = serve(NoWayBack)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, "--index-first", site + "/p/4", cwd=tmp_path)
    assert done.returncode == 2, "a usage error: the walk has to be told where the comic starts\n" + done.stdout[-400:]
    assert "No first-page link found" in done.stdout, done.stdout[-400:]
    assert "--start" in done.stdout, "it says what to do about it"
    assert not index.exists(), "an index begun at page 4 would call page 4 page 1"


@pytest.mark.browser
def test_a_librarys_own_first_page_path_is_used(tmp_path, serve, config):
    site = serve(OwnButton)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, "--index-first", site + "/p/4", cwd=tmp_path)
    assert done.returncode == 2, "no shipped path knows this site's way back\n" + done.stdout[-400:]
    with open(config / "element_paths.json", "w", encoding="utf-8") as f:
        json.dump({"first": [{"xpath": '//a[@class="to-start"]', "note": "Own Button", "enabled": True}]}, f)
    done = run("mirror_base.py", "--index", index, "--index-first", site + "/p/4", cwd=tmp_path)
    assert done.returncode == 0, done.stdout[-400:]
    assert walked(index) == [str(n) for n in range(1, PAGES + 1)]


def test_the_first_page_paths_are_listed_with_the_others(web, config):
    from comiclib.elements import shipped
    code, data = web().call("/api/elements")
    assert code == 200, data
    assert [entry["xpath"] for entry in data["first"]] == [entry["xpath"] for entry in shipped["first"]]
    assert all(entry["note"] for entry in data["first"]), "each says what it is for"


def test_a_save_that_says_nothing_of_first_page_paths_keeps_them(web, config):
    #a page loaded before the first-page list existed sends only the other two
    page = web()
    _, data = page.call("/api/elements")
    own = {"xpath": '//a[@class="to-start"]', "note": "Own Button", "enabled": True}
    assert page.call("/api/elements", {"image": data["image"], "next": data["next"],
                                       "first": [own] + data["first"]})[0] == 200
    assert page.call("/api/elements", {"image": data["image"], "next": data["next"]})[0] == 200
    with open(config / "element_paths.json", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["first"][0]["xpath"] == own["xpath"], "the library's own path is still there, still first"
