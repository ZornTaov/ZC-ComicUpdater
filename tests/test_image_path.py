#the image path a scrape remembers, and what happens on a page where it finds nothing. a site with a menu drawn
#as a picture below every comic, and one page where the comic is not a picture at all, once made a path that
#matched the menu the comic's for good - thousands of pages saved as the menu. no browser and no network: a
#fake page answers each path, and fetch is replaced.
import pytest

from comiclib import elements
from comiclib.exits import REPEATS
from conftest import scrape_args
from test_multipage import FakeAnswer, FakeElement, folder, mb, pages, save  # noqa: F401

REMEMBERED = '//*[@id="comic"]/img[1]'
LOOSER = '//*[@id="comic"]//img'
CONTAINER = '//*[@id="comic"]'
#a path that is right for some other site, and on this one finds the menu below the comic
MENU_PATH = '//*[@id="bottom"]/img'
MENU = "https://example.com/s/menu.jpg"


class Page(object):
    #one page at a time, answering each path with what it would find there
    def __init__(self, mb):
        self.mb = mb
        self.current_url = None
        self.title = "fake"
        self.found = {}

    def at(self, url, **found):
        self.current_url = url
        self.found = {"comic": found.get("comic"), "loose": found.get("loose"), "menu": True,
                      "container": found.get("container", True)}
        return self

    def find_elements(self, by, xpath):
        found = self.found
        if xpath == REMEMBERED and found["comic"]:
            return [FakeElement(found["comic"])]
        if xpath == LOOSER and (found["comic"] or found["loose"]):
            return [FakeElement(found["comic"] or found["loose"])]
        if xpath == CONTAINER and found["container"]:
            return [FakeElement(None)]
        if xpath == MENU_PATH and found["menu"]:
            return [FakeElement(MENU)]
        return []

    def find_element(self, by, xpath):
        raise self.mb.se.NoSuchElementException(xpath)


@pytest.fixture
def scrape(mb):
    #the list as a library with someone else's path ahead of the shipped ones has it, and the comic's own
    #path remembered from earlier runs
    mb.element_names = [MENU_PATH, LOOSER]
    mb.image_xpath = REMEMBERED
    mb.fallbacks_in_row = 0
    mb.scrape_state["repeat_src"], mb.scrape_state["repeat_files"] = None, []
    return mb


def comic(n):
    return "https://example.com/comics/strip_{0}.png".format(n)


def test_a_comic_wrapped_in_a_link_is_found_where_the_comic_always_is(scrape, folder):
    page = Page(scrape)
    said, nxt = save(scrape, page.at("https://example.com/1/", comic=comic(1)), scrape_args(folder), 1)
    said, nxt = save(scrape, page.at("https://example.com/2/", loose=comic(2)), scrape_args(folder), nxt)
    assert pages(scrape, folder) == ["0001_strip_1.png", "0002_strip_2.png"], "not the menu below it"
    assert scrape.image_xpath == REMEMBERED, "the comic's own path stays the comic's"


def test_a_page_whose_comic_is_not_a_picture_is_kept_as_a_note_of_its_address(scrape, folder):
    page = Page(scrape)
    said, nxt = save(scrape, page.at("https://example.com/1/", comic=comic(1)), scrape_args(folder), 1)
    said, nxt = save(scrape, page.at("https://example.com/2/"), scrape_args(folder), nxt)
    assert "holds no picture where this comic's pages are" in said, said
    assert pages(scrape, folder) == ["0001_strip_1.png", "0002_link.url"]
    with open(folder + "/0002_link.url", encoding="utf-8") as f:
        assert "URL=https://example.com/2/" in f.read()
    said, nxt = save(scrape, page.at("https://example.com/3/", comic=comic(3)), scrape_args(folder), nxt)
    assert pages(scrape, folder)[-1] == "0003_strip_3.png" and scrape.image_xpath == REMEMBERED


def test_one_odd_page_does_not_make_another_path_the_comics(scrape, folder):
    #the comic's container is gone from one page: the list finds the menu there, for that page only
    page = Page(scrape)
    said, nxt = save(scrape, page.at("https://example.com/1/", comic=comic(1)), scrape_args(folder), 1)
    said, nxt = save(scrape, page.at("https://example.com/2/", container=False), scrape_args(folder), nxt)
    assert "for this page only" in said, said
    said, nxt = save(scrape, page.at("https://example.com/3/", comic=comic(3)), scrape_args(folder), nxt)
    assert scrape.image_xpath == REMEMBERED
    assert pages(scrape, folder)[-1] == "0003_strip_3.png", "back to the comic on the very next page"


def test_a_site_that_changed_its_layout_moves_to_the_path_that_finds_it(scrape, folder):
    page = Page(scrape)
    #the menu path stands in for a site's new layout here; three pages running is a change, not an odd page
    nxt = 1
    for n in range(1, 4):
        said, nxt = save(scrape, page.at("https://example.com/{0}/".format(n), container=False),
                         scrape_args(folder), nxt)
    assert scrape.image_xpath == MENU_PATH
    assert "now found by" in said, said


def test_the_same_picture_on_page_after_page_stops_the_run(scrape, folder):
    page = Page(scrape)
    #a run whose remembered path is the one that finds the menu, as a run once was
    scrape.image_xpath = MENU_PATH
    nxt = 1
    with pytest.raises(scrape.MirrorError) as stopped:
        for n in range(1, 10):
            said, nxt = save(scrape, page.at("https://example.com/{0}/".format(n)), scrape_args(folder), nxt)
    assert stopped.value.code == REPEATS
    assert "found as the comic on 5 pages in a row" in str(stopped.value) and MENU_PATH in str(stopped.value)
    assert len(pages(scrape, folder)) == 4, "it stops before writing the fifth"
    assert "0001_menu.jpg to 0004_menu.jpg" in str(stopped.value), "and names the pages to take out"


@pytest.mark.parametrize("path, container", [
    ('//*[@id="comic"]/img[1]', '//*[@id="comic"]'),
    ('//*[@id="comic"]//img', '//*[@id="comic"]'),
    ('//*[@class="comicpage"]/a/img', '//*[@class="comicpage"]/a'),
    ('//img[@id="cc-comic"]', None),
    ('/html/body/div/img', None),
    ('//*[@id="content"]/article/img|//*[@id="content"]/article/a/img', None),
    ('//img[starts-with(@src, "comics/")]', None),
])
def test_where_a_path_looks(path, container):
    assert elements.container_of(path) == container
