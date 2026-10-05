#an archive page that draws its chapter headings as pictures and lists each chapter's pages in a table of
#its own. no browser and no network: the archives are made up here.


def read(chapters, html, pages):
    #pages: the addresses a walk would have found, in order, which is what turns a link into a page number
    where = {chapters.same_page(url): at + 1 for at, url in enumerate(pages)}
    reader = chapters.ArchiveReader()
    reader.feed(html)
    found, listed = chapters.chapters_from_events(reader.events, where, "https://comic.example.com/archive")
    return found, listed, reader.events


def drawn(per):
    #everything wrapped in a container named "chapters", each chapter headed by a picture and holding its
    #pages in a table named after the chapter
    out = ['<html><body><div id="chapters"><center><table>']
    at = 0
    for chapter in range(1, len(per) + 1):
        out.append('<tr><td><center><img height="250px" src="chapter{0}.png"></center><br>'.format(chapter))
        out.append('<center><table id="chapter{0}_table">'.format(chapter))
        for _ in range(per[chapter - 1]):
            out.append('<tr><td><a href= "pages.php#{0:04d}">{0:04d}</a></td><td>|</td></tr>'.format(at + 1))
            at += 1
        out.append('</table></center></td></tr>')
    out.append('</table></center></div></body></html>')
    return "".join(out), ['https://comic.example.com/pages.php#{0:04d}'.format(n + 1) for n in range(at)]


def test_a_drawn_heading_over_a_table_of_page_links_names_a_chapter(chapters):
    html, pages = drawn([3, 4, 2])
    found, listed, events = read(chapters, html, pages)
    assert listed == 9, "every page link is read as a page"
    assert len(found) == 3, "one chapter per drawn heading, not one per link"
    assert [c["label"] for c in found] == ["Chapter 1", "Chapter 2", "Chapter 3"], "named from the picture"
    assert [c["start_page"] for c in found] == [1, 4, 8], "each starting where its own table starts"
    headings = [e for e in events if e[0] == "heading"]
    assert len(headings) == 3, "the container named chapters heads nothing of its own: {0}".format(headings)


def test_a_written_heading_still_wins_over_the_picture_in_it(chapters):
    html = ('<html><body><h2><img src="chapter9.png" alt="ignored"> Chapter Nine: The Fall</h2>'
            '<a href="/p/1">1</a><a href="/p/2">2</a></body></html>')
    found, listed, events = read(chapters, html, ['https://comic.example.com/p/1', 'https://comic.example.com/p/2'])
    assert len(found) == 1, found
    assert found[0]["label"] == "Chapter Nine: The Fall", "named by its words, not by its picture"


def test_a_heading_that_holds_its_own_link_still_names_that_chapter(chapters):
    html = ('<html><body><h3><a href="/p/5">Chapter Two</a></h3>'
            '<h3><a href="/p/9">Chapter Three</a></h3></body></html>')
    pages = ['https://comic.example.com/p/{0}'.format(n) for n in range(1, 12)]
    found, listed, events = read(chapters, html, pages)
    assert len(found) == 2, found
    assert [c["label"] for c in found] == ["Chapter Two", "Chapter Three"], "named by the heading round its link"
    assert [c["start_page"] for c in found] == [5, 9], "starting at the page it links to"


def test_a_comic_told_in_stories_listed_newest_first_is_cut_at_each_story(chapters):
    #three long stories, each a picture captioned "Story N" that links to the story's first page, over its
    #pages in columns, newest first. each page is titled for its storyline, which is not a chapter, and one
    #of them has "Story" in its title
    starts = [1, 6, 11]
    titles = {n: "#{0}: Silliness - Page {0}".format(n) for n in range(1, 14)}
    titles[4] = "#4: Filler - A Bedtime Story"
    titles[6] = "#6: Story 2"
    out = ['<html><body><center>']
    for story, first in reversed(list(enumerate(starts, 1))):
        last = (starts + [14])[story] - 1
        out.append('<table><tr><td><a name="story{0}" href="{1}"><img src="images/Story{0}.png" alt="Story {0}" />'
                   '</a></td></tr><tr><td>'.format(story, first))
        for n in range(last, first - 1, -1):
            out.append('<a href="{0}">{1}</a><br/>'.format(n, titles[n]))
            if n == (first + last) // 2:
                out.append('</td><td>')
        out.append('</td></tr></table><br/>')
    out.append('<a href="index.php"><img src="images/index.png" alt="Main Page" /></a></center></body></html>')
    walk = [{"n": n, "url": "https://comic.example.com/{0}".format(n)} for n in range(1, 14)]
    reader = chapters.ArchiveReader()
    reader.feed("".join(out))
    found, listed = chapters.chapters_from_events(reader.events, chapters.first_of_each(walk),
                                                  "https://comic.example.com/archive-list.php")
    assert listed == 13, "every page link is read as a page"
    settled = [(c["label"], c["start_page"], c["pages"]) for c in chapters.settle_chapters(found, walk)]
    assert settled == [("Story 1", 1, 5), ("Story 2", 6, 5), ("Story 3", 11, 3)], \
        "one chapter per story, in reading order, each starting where its picture links"


def test_pictures_that_are_not_headings_head_nothing(chapters):
    for name in ("banner.png", "partners.png", "bookmark.png", "logo.gif", "next.png"):
        assert chapters.drawn_heading({"src": name}) is None, name


def test_a_picture_named_for_a_chapter_reads_as_one(chapters):
    for name, want in (("chapter1.png", "Chapter 1"), ("chapter_12.png", "Chapter 12"),
                       ("Arc-3.jpg", "Arc 3"), ("volume2.png", "Volume 2"), ("PaintStory3.png", None),
                       ("story_3.png", "Story 3")):
        assert chapters.drawn_heading({"src": name}) == want, name
    assert chapters.drawn_heading({"src": "chapter1.png", "alt": "Chapter 1: The Start"}) == "Chapter 1: The Start", \
        "an alt is preferred to the filename"
