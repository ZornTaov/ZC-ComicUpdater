#several pages on one address: detection, numbering, the index and what gets left out.
#no browser and no network - a fake driver hands back the srcs a real page would, and fetch is replaced.
import contextlib
import io
import json
import os

import pytest

from conftest import scrape_args

COMIC = '//*[@alt="Comic"]'


class FakeElement(object):
    def __init__(self, src):
        self.src = src

    def get_attribute(self, name):
        return self.src if name == 'src' else None


class FakeDriver(object):
    #one page at a time: whatever setup() calls the page, find_elements answers for this xpath only
    def __init__(self, mb):
        self.mb = mb
        self.current_url = None
        self.title = "fake"
        self.srcs = []
        self.xpath = COMIC

    def at(self, url, srcs):
        self.current_url = url
        self.srcs = list(srcs)
        return self

    def find_elements(self, by, xpath):
        return [FakeElement(src) for src in self.srcs] if xpath == self.xpath else []

    def find_element(self, by, xpath):
        raise self.mb.se.NoSuchElementException(xpath)


class FakeAnswer(object):
    def __init__(self, src):
        #distinct bytes per image, so a page written over another one would show
        self.content = ("image of " + src).encode('utf-8')


@pytest.fixture
def mb(mirror):
    #a clean run state, as setup() would leave it, and every download answered from here
    mirror.fetch = lambda src, attempts=3: FakeAnswer(src)
    mirror.image_xpath = None
    mirror.last_page_url = None
    mirror.last_page_srcs = set()
    mirror.seen_on_pages = {}
    mirror.existing_pages = {}
    mirror.visited_urls = set()
    mirror.index_file = None
    mirror.index_urls = set()
    mirror.index_pages = set()
    mirror.index_last = 0
    mirror.run_id = "test"
    mirror.run_start = mirror.now_stamp()
    for key, value in (("first_page_url", None), ("first_increment", None), ("last_page_url", None),
                       ("last_increment", None), ("last_image_src", None), ("last_image_file", None),
                       ("pages_saved", 0), ("last_known_number", None), ("fresh_pages", 0),
                       ("backwards_run", 0), ("most_per_url", 0), ("first_multi_url", None),
                       ("multi_urls", 0)):
        mirror.scrape_state[key] = value
    return mirror


@pytest.fixture
def folder(tmp_path):
    out = tmp_path / "comic"
    out.mkdir()
    return str(out)


def save(mb, driver, args, increment):
    #the loop's own numbering: asked of the state, not counted, so an address of several pages advances by
    #as many as it held
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mb.img_save(driver, increment, "png", args)
    last = mb.scrape_state["last_increment"]
    return out.getvalue(), increment + 1 if last is None else last + 1


def pages(mb, folder):
    return sorted(n for n in os.listdir(folder) if n != mb.metadata_file)


def several(n, host="https://example.com/comic"):
    return ["{0}/12_3_{1}.jpeg".format(host, at) for at in range(1, n + 1)]


def test_several_pages_on_one_address_are_all_saved_and_the_buttons_left_out(mb, folder):
    #six pages on one address, with the site's rss and share buttons caught by the same loose path
    driver = FakeDriver(mb).at("https://example.com/comic/12_3",
                               several(6, "https://www.example.com/comic/pages")
                               + ["https://example.com/comic/rss.png", "https://example.com/comic/share.png"])
    said, nxt = save(mb, driver, scrape_args(folder), 1)
    assert pages(mb, folder) == ["000{0}_12_3_{0}.jpeg.png".format(n) for n in range(1, 7)]
    assert "rss.png" in said and "carry no page number" in said, said
    assert "https://example.com/comic/12_3: ignoring" in said, "the page it happened on is named"
    assert "holds 6 pages of the comic, so this comic puts several" in said, said
    assert nxt == 7, "the next address carries on from the last page saved"


def test_a_comic_that_starts_putting_several_pages_on_an_address_partway(mb, folder):
    driver = FakeDriver(mb)
    said, nxt = save(mb, driver.at("https://example.com/300.html", ["https://example.com/300.png"]),
                     scrape_args(folder), 300)
    assert pages(mb, folder) == ["0300_300.png"], "a single page still saves as one page"
    assert "several pages" not in said, "nothing is said while each address holds one page"

    said, nxt = save(mb, driver.at("https://example.com/304.html",
                                   ["https://example.com/304({0}).png".format(c) for c in "fgh"]),
                     scrape_args(folder), nxt)
    assert "has started putting several pages on one address" in said, "the change is reported when it happens"
    assert pages(mb, folder) == ["0300_300.png", "0301_304(f).png", "0302_304(g).png", "0303_304(h).png"], \
        "each page of the address gets its own number"
    assert nxt == 304, "numbering carries on past the address"

    said, nxt = save(mb, driver.at("https://example.com/305.html",
                                   ["https://example.com/305({0}).png".format(c) for c in "ab"]),
                     scrape_args(folder), nxt)
    assert "several pages" not in said, "the change is only reported once"


def test_no_multi_page_saves_only_the_first(mb, folder):
    driver = FakeDriver(mb).at("https://example.com/comic/12_3", several(3, "https://www.example.com/comic/pages"))
    save(mb, driver, scrape_args(folder, multi_page=False), 1)
    assert pages(mb, folder) == ["0001_12_3_1.jpeg.png"]


def test_every_image_is_a_page_when_none_of_them_carries_a_number(mb, folder):
    driver = FakeDriver(mb).at("https://example.com/one", ["https://example.com/a.png", "https://example.com/b.png"])
    save(mb, driver, scrape_args(folder), 1)
    assert pages(mb, folder) == ["0001_a.png", "0002_b.png"]


def test_the_index_gets_a_line_per_page_not_per_address(mb, folder):
    mb.index_file = os.path.join(folder, "index.jsonl")
    open(mb.index_file, 'w').close()
    driver = FakeDriver(mb).at("https://example.com/12_3", several(3, "https://example.com"))
    save(mb, driver, scrape_args(folder), 1)
    with io.open(mb.index_file, encoding='utf-8') as f:
        lines = [json.loads(one) for one in f if one.strip()]
    assert len(lines) == 3, lines
    assert [(one["n"], one["file"]) for one in lines] == \
        [(1, "0001_12_3_1.jpeg.png"), (2, "0002_12_3_2.jpeg.png"), (3, "0003_12_3_3.jpeg.png")], \
        "each index line names its own image and number"
    assert {one["url"] for one in lines} == {"https://example.com/12_3"}, "the lines all name the one address"


def test_the_metadata_records_what_a_later_run_needs_to_know(mb, folder):
    driver = FakeDriver(mb).at("https://example.com/12_3", several(3, "https://example.com"))
    save(mb, driver, scrape_args(folder), 5)
    with io.open(os.path.join(folder, mb.metadata_file), encoding='utf-8') as f:
        meta = json.load(f)
    assert meta["state"].get("pages_per_url") == 3, "how many pages an address holds"
    assert meta["state"].get("multi_page_from") == "https://example.com/12_3", "which address first held several"
    assert meta["settings"]["increment"] == 7, "the resume number is past the last page saved, not the first"
    assert meta["settings"].get("multi_page") is True, \
        "saving every page an address holds is written down as a setting"


def test_a_resume_drops_the_older_name_of_every_page_on_the_address(mb, folder):
    #a resume re-saves the whole address it stopped on, and the old names for those pages give way
    for old in (5, 6):
        #named by hand as just the number, the way a mirror made before this script was
        with open(os.path.join(folder, "{0}.png".format(str(old).zfill(4))), 'wb') as f:
            f.write(b"an older name for this page")
    driver = FakeDriver(mb).at("https://example.com/12_3", several(3, "https://example.com"))
    said, nxt = save(mb, driver, scrape_args(folder), 5)
    assert pages(mb, folder) == ["0005_12_3_1.jpeg.png", "0006_12_3_2.jpeg.png", "0007_12_3_3.jpeg.png"], \
        "the older name of every page on the address is dropped, not just the first"
    assert said.count("superseded by") == 2, "dropping them is said out loud"


def test_comic_images_on_its_own(mb):
    assert mb.comic_images(["https://example.com/next.png"]) == ["https://example.com/next.png"], \
        "one image is never filtered"
    assert mb.comic_images(["https://example.com/1.png", "https://example.com/next.png?v=2"]) == \
        ["https://example.com/1.png"], "a query string does not make a button a page"
    driver = FakeDriver(mb).at("u", ["https://example.com/1.png", "https://example.com/1.png"])
    assert mb.ele_get_all(driver, COMIC) == ["https://example.com/1.png"], "the same image twice is one page"


NAV = ["https://example.com/nav/first.png", "https://example.com/nav/archive.png"]


def test_the_sites_own_furniture_that_follows_the_comic_is_not_a_page(mb, folder):
    driver = FakeDriver(mb)
    said, nxt = save(mb, driver.at("https://example.com/p/1", [NAV[0], "https://example.com/img/0001.png", NAV[1]]),
                     scrape_args(folder), 1)
    assert pages(mb, folder) == ["0001_0001.png"], "the first page of a run keeps what it finds"
    save(mb, driver.at("https://example.com/p/2", [NAV[0], "https://example.com/img/0002.png", NAV[1]]),
         scrape_args(folder), nxt)
    assert pages(mb, folder) == ["0001_0001.png", "0002_0002.png"], "an image that was on the page before is not a page"


def test_only_the_page_is_kept_where_none_of_the_images_is_numbered(mb, folder):
    #the case numbering cannot help with
    driver = FakeDriver(mb)
    said, nxt = save(mb, driver.at("https://example.com/p/1", [NAV[0], "https://example.com/img/0001.png", NAV[1]]),
                     scrape_args(folder), 1)
    save(mb, driver.at("https://example.com/p/2", [NAV[0], "https://example.com/book.gif", NAV[1]]),
         scrape_args(folder), nxt)
    assert pages(mb, folder) == ["0001_0001.png", "0002_book.gif"]


def test_the_same_page_twice_over_is_not_a_page_made_of_furniture(mb, folder):
    driver = FakeDriver(mb)
    same = [NAV[0], "https://example.com/img/0001.png"]
    said, nxt = save(mb, driver.at("https://example.com/p/1", same), scrape_args(folder), 1)
    save(mb, driver.at("https://example.com/p/1b", same), scrape_args(folder), nxt)
    #nothing is dropped for repeating, so the numbering rule has its usual say and the page is saved again
    assert pages(mb, folder) == ["0001_0001.png", "0002_0001.png"]
