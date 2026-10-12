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


SHORTCUTS = """
<h2>Chapter 1</h2><a href="/comic/p1">Chapter 1</a>
<h2>Chapter 2</h2><a href="/comic/p6">Chapter 2</a>
<h2>Intermission: A Birthday</h2><a href="/comic/p11">Intermission: A Birthday</a>
<h2>Chapter 3</h2><a href="/comic/p12">Chapter 3</a>
<h2>Chapter 4</h2><a href="/comic/p16">Chapter 4</a>
<p>Favourite moments</p>
<h3>Trauma in the shower</h3><a href="/comic/p9">Trauma in the shower</a>
<h3>Talk Like a Pirate</h3><a href="/comic/p14">Talk Like a Pirate</a>
"""


def test_shortcuts_into_the_middle_of_chapters_listed_after_them_start_nothing(chapters):
    #an archive that lists its chapters in order, then, far below them, links to favourite moments in the
    #middle of some. each points back before the last chapter listed, which no chapter of a run does: they
    #are shortcuts, and the pages they lead to stay in the chapter they were published in
    found = parse(chapters, SHORTCUTS, SITE)
    assert [(c["label"], c["start_page"]) for c in found] == [
        ("Chapter 1", 1), ("Chapter 2", 6), ("Intermission: A Birthday", 11), ("Chapter 3", 12), ("Chapter 4", 16)]


def test_shortcuts_to_pages_the_chapters_already_list_start_nothing_either(chapters):
    #each chapter listing every one of its pages, then a gallery below that links back to pages among them:
    #a page already listed is still not where a chapter starts when it is linked from out of order
    every_page = """
    <h2>Chapter 1</h2>""" + "".join('<a href="/comic/p{0}">{0}</a>'.format(n) for n in range(1, 6)) + """
    <h2>Chapter 2</h2>""" + "".join('<a href="/comic/p{0}">{0}</a>'.format(n) for n in range(6, 11)) + """
    <h2>Chapter 3</h2>""" + "".join('<a href="/comic/p{0}">{0}</a>'.format(n) for n in range(11, 16)) + """
    <h2>Chapter 4</h2>""" + "".join('<a href="/comic/p{0}">{0}</a>'.format(n) for n in range(16, 21)) + """
    <h2>Buried Treasure</h2>
    <h3>Art: a favourite page</h3><a href="/comic/p8">it</a>
    <h3>April Fools</h3><a href="/comic/p13">it</a>
    """
    found = parse(chapters, every_page, SITE)
    assert [c["start_page"] for c in found] == [1, 6, 11, 16]


def test_shortcuts_after_an_archive_listed_newest_first_start_nothing_either(chapters):
    newest_first = """
    <h2>Chapter 4</h2><a href="/comic/p16">Chapter 4</a>
    <h2>Chapter 3</h2><a href="/comic/p11">Chapter 3</a>
    <h2>Chapter 2</h2><a href="/comic/p6">Chapter 2</a>
    <h2>Chapter 1</h2><a href="/comic/p1">Chapter 1</a>
    <h3>A favourite moment</h3><a href="/comic/p13">A favourite moment</a>
    """
    found = parse(chapters, newest_first, SITE)
    assert sorted(c["start_page"] for c in found) == [1, 6, 11, 16]


def test_headings_leading_to_files_are_never_fetched_and_a_shared_page_is_read_once(chapters):
    #an archive whose chapters lead to pages of their own, and under other headings a shop, a picture and a
    #whole volume as a zip. the zip took minutes to download only to be read as a page
    html_text = """
    <h2>Chapter 1</h2><a href="/chapters/one">Chapter 1</a>
    <h2>Chapter 2</h2><a href="/chapters/two">Chapter 2</a>
    <h2>Volume one, as an ebook</h2><a href="/misc/ebooks/vol1.zip">Download</a>
    <h2>A page that never was</h2><a href="/img/graveyard/unused.png">See it</a>
    <h2>Volume four</h2><a href="/store/#volumefour">Buy</a>
    <h2>Volume five</h2><a href="/store/#volumefive">Buy</a>
    """
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url.endswith("/one"):
            return '<a href="/comic/p1">1</a><a href="/comic/p2">2</a>'
        if url.endswith("/two"):
            return '<a href="/comic/p8">8</a><a href="/comic/p9">9</a>'
        return "<p>the shop</p>"
    reader = chapters.ArchiveReader()
    reader.feed(html_text)
    where = {chapters.same_page(p["url"]): p["n"] for p in SITE}
    found = chapters.chapters_from_events(reader.events, where, "https://x.test/archive/", fetch=fetch)[0]
    assert [(c["label"], c["start_page"]) for c in found] == [("Chapter 1", 1), ("Chapter 2", 8)]
    assert not any(url.endswith((".zip", ".png")) for url in fetched), fetched
    assert sum("/store/" in url for url in fetched) == 1, "the shop page is read once for both its headings"


def test_a_chapter_put_in_is_said_as_put_in_not_as_every_later_chapter_moving(chapters):
    was = [{"start_page": 1, "label": "Chapter 1"}, {"start_page": 6, "label": "Chapter 2"},
           {"start_page": 11, "label": "Extras"}, {"start_page": 16, "label": "Chapter 3"}]
    now = [{"start_page": 1, "label": "Chapter 1"}, {"start_page": 4, "label": "A Special"},
           {"start_page": 6, "label": "Chapter 2"}, {"start_page": 11, "label": "Bonus"},
           {"start_page": 16, "label": "Chapter 3"}]
    how, what = chapters.compare_chapters(was, now)
    assert how == "changed"
    assert what == ["adds A Special at page 4, inside Chapter 1", "renames Extras to Bonus at page 11"]
    how, what = chapters.compare_chapters(was, [c for c in was if c["label"] != "Extras"])
    assert what == ["drops Extras at page 11, its pages joining Chapter 2"]


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
