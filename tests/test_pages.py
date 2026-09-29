#what a filename says about a page, from comiclib.pages: the name a scrape gives an image, and that name
#read back as a page.
import pytest

from comiclib.pages import page_key, page_number, saved_name


@pytest.mark.parametrize("src, name", [
    ("https://example.com/comics/0001.png", "0001.png"),
    #an address with no extension gets one, and a gif stays a gif
    ("https://example.com/comics/page-one", "page-one.png"),
    ("https://example.com/comics/moving.gif", "moving.gif"),
    #a query string or a fragment is not part of the name: page.png?v=2 is page.png
    ("https://example.com/comics/0002.png?v=2", "0002.png"),
    ("https://example.com/comics/0003.jpg#top", "0003.jpg.png"),
    ("https://example.com/image.php?id=40", "image.php.png"),
    ("https://example.com/comics/0004/", "0004.png"),
], ids=["plain", "no extension", "gif", "query", "fragment", "script with a query", "trailing slash"])
def test_the_name_a_scrape_gives_an_image(src, name):
    assert saved_name(src) == name


def test_a_saved_name_reads_back_as_the_same_page():
    #numbered or not, the page a name was saved as is the page it reads as
    name = saved_name("https://example.com/comics/0042.png?cache=1")
    assert page_key("0042_" + name) == page_key(name)
    assert page_number("0042_" + name) == 42
