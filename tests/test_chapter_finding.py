#where a comic's chapters begin, worked out from the addresses of its pages or read off its archive page,
#and settled so every page lands in exactly one chapter, in reading order.
import pytest


def pages_at(urls):
    return [{"n": at + 1, "url": url, "file": "{0:04d}.png".format(at + 1)} for at, url in enumerate(urls)]


def labels(found):
    return [c["label"] for c in found]


SITE = pages_at(["https://x.test/comic/p{0}".format(n) for n in range(1, 21)])


def parse(chapters, html_text, pages, base="https://x.test/archive/"):
    reader = chapters.ArchiveReader()
    reader.feed(html_text)
    where = {chapters.same_page(p["url"]): p["n"] for p in pages}
    return chapters.chapters_from_events(reader.events, where, base)[0]


def test_chapters_are_read_out_of_the_addresses_themselves(chapters):
    numbered = pages_at(["https://example.com/c{0}/p{1}".format(c, p)
                         for c, n in ((1, 20), (2, 15), (3, 18)) for p in range(1, n + 1)])
    found = chapters.settle_chapters(chapters.chapters_from_urls(numbered), numbered)
    assert [c["pages"] for c in found] == [20, 15, 18], "three chapters from /c#/p#"
    assert labels(found) == ["Chapter 1", "Chapter 2", "Chapter 3"], "labelled by their own number"

    #a path whose first step is letters: the letters are not mistaken for a chapter
    dashed = pages_at(["https://example.com/ss/{0}-{1}".format(c, p)
                       for c, n in ((1, 9), (2, 12), (3, 7)) for p in range(1, n + 1)])
    found = chapters.settle_chapters(chapters.chapters_from_urls(dashed), dashed)
    assert [c["pages"] for c in found] == [9, 12, 7], "/ss/#-# works the same"


def test_a_comic_numbered_straight_through_or_by_date_has_no_chapters(chapters):
    flat = pages_at(["https://example.com/strip/{0}".format(n) for n in range(1, 40)])
    assert chapters.chapters_from_urls(flat) == []
    dated = pages_at(["https://example.com/99/2014-01-{0:02d}".format(n) for n in range(1, 28)])
    assert chapters.chapters_from_urls(dated) == [], "dates are not chapters"


def issues():
    #a comic whose addresses name the issue and number its pages within it, each issue opening on a cover
    urls = []
    for issue, held in ((1, 25), (2, 24), (3, 26)):
        urls.append("https://example.com/comic/issue-{0}-cover/".format(issue))
        urls += ["https://example.com/comic/issue-{0}-page-{1}/".format(issue, p) for p in range(1, held)]
    return urls


def test_chapters_named_in_the_address_rather_than_numbered_in_the_path(chapters):
    urls = issues()
    found = chapters.settle_chapters(chapters.chapters_from_urls(pages_at(urls)), pages_at(urls))
    assert [c["pages"] for c in found] == [25, 24, 26], "three issues out of issue-N-page-M"
    assert labels(found) == ["Issue 1", "Issue 2", "Issue 3"], "named as issues, not chapters"
    assert found[0]["start_page"] == 1 and found[1]["start_page"] == 26, \
        "the page number in the slug is not mistaken for the chapter"


def test_a_stray_page_or_a_plural_typo_does_not_make_a_chapter(chapters):
    strays = issues()
    strays.insert(25, "https://example.com/comic/a-one-off-special/")   # a one-off slug
    strays.insert(30, "https://example.com/comic/issues-2-page-extra/")  # a typo on the site
    found = chapters.settle_chapters(chapters.chapters_from_urls(pages_at(strays)), pages_at(strays))
    assert len(found) == 3, "a stray page does not become a chapter of its own: {0}".format(labels(found))
    assert labels(found) == ["Issue 1", "Issue 2", "Issue 3"], "a plural typo does not split one in two"
    assert sum(c["pages"] for c in found) == len(strays), "every page still lands somewhere"


ARCHIVE = """<html><body>
  <h3 class="comic-archive-chapter">The Start</h3>
  <span class="comic-archive-date">Jan 01, 2005</span>
  <a href="https://x.test/comic/p1">first</a>
  <a href="http://X.TEST/comic/p2/">second, written differently</a>
  <h3 class="comic-archive-chapter">The Middle</h3>
  <a href="/comic/p9">ninth</a>
  <a href="https://x.test/somewhere/else">not a page of this comic</a>
  <h3 class="comic-archive-chapter">The End</h3>
  <a href="https://x.test/comic/p15">fifteenth</a>
</body></html>"""


def test_chapters_are_read_off_an_archive_page(chapters):
    found = chapters.settle_chapters(parse(chapters, ARCHIVE, SITE), SITE)
    assert len(found) == 3, found
    assert labels(found) == ["The Start", "The Middle", "The End"], "labels come from the headings"
    assert [c["start_page"] for c in found] == [1, 9, 15], \
        "http vs https, www and a trailing slash all count as the same page"
    assert [c["pages"] for c in found] == [8, 6, 6], "a link to somewhere else is ignored"


def test_pages_the_archive_never_lists_stay_in_the_chapter_they_were_published_in(chapters):
    found = chapters.settle_chapters(parse(chapters, ARCHIVE, SITE), SITE)
    assert found[0]["end_page"] == 8 and found[1]["start_page"] == 9, found


def test_a_date_class_is_not_a_heading_though_it_holds_the_letters_of_arc(chapters):
    reader = chapters.ArchiveReader()
    reader.feed('<span class="comic-archive-date">Jan 01, 2005</span><a href="https://x.test/comic/p1">x</a>')
    assert not [e for e in reader.events if e[0] == "heading"], reader.events


def test_an_archive_that_labels_a_chapter_after_its_first_page_can_be_shifted(chapters):
    late = [{"label": "One", "start_page": 2, "pages_listed": [2]},
            {"label": "Two", "start_page": 10, "pages_listed": [10]}]
    found = chapters.settle_chapters([dict(c) for c in late], SITE, shift=-1)
    assert [c["start_page"] for c in found] == [1, 9], "every boundary moves back one"


def test_two_headings_pointing_at_one_page_make_one_chapter(chapters):
    same = [{"label": "A", "start_page": 5, "pages_listed": [5]},
            {"label": "B", "start_page": 5, "pages_listed": [5]}]
    assert len(chapters.settle_chapters(same, SITE)) == 1


def test_chapters_are_numbered_in_reading_order_whatever_the_labels_say(chapters):
    odd = [{"label": "2019 specials", "start_page": 12, "pages_listed": [12]},
           {"label": "Chapter 1", "start_page": 1, "pages_listed": [1]},
           {"label": "Chapter 2", "start_page": 6, "pages_listed": [6]}]
    found = chapters.settle_chapters(odd, SITE)
    assert [(c["number"], c["label"]) for c in found] == [(1, "Chapter 1"), (2, "Chapter 2"), (3, "2019 specials")]
    assert found[-1]["end_page"] == 20, "the last chapter runs to the end of the comic"
    assert sum(c["pages"] for c in found) == 20 and found[0]["start_page"] == 1, \
        "every page lands in exactly one chapter"


def test_the_chapter_title_wins_over_the_summary_and_the_site_banner(chapters):
    layered = """<html><body>
      <h1>The Whole Site</h1><h2>Adventure</h2>
      <h3 class="comic-archive-chapter">Chapter 1</h3>
      <div class="comic-archive-chapter-description">The hero accepts the quest, and learns what it costs.</div>
      <a href="https://x.test/comic/p1">start</a>
      <h3 class="comic-archive-chapter">Chapter 2</h3>
      <div class="comic-archive-chapter-description">A summary nobody wants as a title.</div>
      <a href="https://x.test/comic/p7">later</a>
    </body></html>"""
    found = chapters.settle_chapters(parse(chapters, layered, SITE), SITE)
    assert labels(found) == ["Chapter 1", "Chapter 2"], "the title wins over the summary under it"
    assert "Adventure" not in labels(found), "and over the site banner above it"


@pytest.mark.parametrize("link, wanted", [
    ("https://comic.example.com/comic/page000/", True),     # another page of the comic
    ("http://COMIC.example.com/comic/page012", True),       # the same, written differently
    ("https://comic.example.com/archive/", False),          # the archive page itself
    ("https://comic.example.com/about/", False),            # some other page of the site
    ("https://x.test/comic/page001/", False),               # another site entirely
])
def test_a_page_of_the_comic_is_told_from_any_other_link_by_its_path(chapters, link, wanted):
    assert chapters.looks_like_pages(link, "https://comic.example.com/comic/page326/") is wanted


@pytest.mark.parametrize("link, wanted", [
    ("https://comic.example.com/index.php?pid=20091116", True),      # a page, by query
    ("https://comic.example.com/archive.php", False),                # the archive itself
    ("https://comic.example.com/archive.php#1", False),              # a jump within the archive
])
def test_a_page_of_the_comic_is_told_from_any_other_link_by_its_query(chapters, link, wanted):
    assert chapters.looks_like_pages(link, "https://comic.example.com/index.php?pid=20080128") is wanted
