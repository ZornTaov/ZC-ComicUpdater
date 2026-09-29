#chapters read off a comic's archive page: which heading names a chapter, which links are pages of the
#comic, and the page counts some archives write into their headings.


def read(chapters, html, base, known):
    #exactly what try_archive does: read the page, take the comic's own pages in the order it lists
    #them, and let the archive's order stand in for the comic's
    reader = chapters.ArchiveReader()
    reader.feed(html)
    links, order = chapters.pages_linked(reader.events, base, known)
    pretend = [{"n": n, "url": u} for n, u in enumerate(links, 1)]
    found, listed = chapters.chapters_from_events(reader.events, order, base)
    return (chapters.settle_chapters(found, pretend) if found and pretend else []), links


def labels(found):
    return [c["label"] for c in found]


def test_a_chapter_is_named_by_the_link_inside_its_heading(chapters):
    archive = "".join('<div class="chapter c{0}"><h4>{0}. <a href="c{0}/p1">Title {0}</a> '
                      '<span class="chapterdetails">({0}&nbsp;pages<span class="date">,&nbsp;5/5/06</span>)'
                      '</span></h4><img src="i.png"><p>A description that is not a title.</p></div>'.format(n)
                      for n in range(1, 6))
    found, links = read(chapters, archive, "https://x.test/archive.html", "https://x.test/c1/p1")
    assert len(found) == 5, labels(found)
    assert labels(found) == ["{0}. Title {0}".format(n) for n in range(1, 6)], \
        "named by its heading, not its description"
    assert [c["pages_said"] for c in found] == [1, 2, 3, 4, 5], \
        "the page count is taken out of the name and kept"
    assert [c["start_url"] for c in found] == ["https://x.test/c{0}/p1".format(n) for n in range(1, 6)]


def test_a_chapter_in_the_first_step_of_the_path_is_still_the_same_comic(chapters):
    first = "https://x.test/c1/p1"
    assert chapters.looks_like_pages("https://x.test/c7/p3", first), "another chapter's page"
    assert chapters.looks_like_pages("https://x.test/c12.1/p1", first), "a sub-numbered chapter"
    assert not chapters.looks_like_pages("https://x.test/archive.html", first), "the archive page itself"
    assert not chapters.looks_like_pages("https://x.test/store/2volumes", first), "another part of the site"
    assert not chapters.looks_like_pages("https://example.com/c2/p1", first), "another site entirely"
    #a comic with one fixed first step still works the old way
    assert chapters.looks_like_pages("https://x.test/comic/issue-4-page-7/", "https://x.test/comic/issue-1-cover/")


def test_a_heading_tag_beats_a_container_whose_class_says_chapter(chapters):
    archive = ('<div class="chapter"><h2><a href="p1">Real Title</a></h2>'
               '<p>Words that are not the title at all.</p></div>'
               '<div class="chapter"><h2><a href="p2">Second</a></h2><p>More words.</p></div>'
               '<div class="chapter"><h2><a href="p3">Third</a></h2></div>'
               '<div class="chapter"><h2><a href="p4">Fourth</a></h2></div>')
    found, links = read(chapters, archive, "https://x.test/a.html", "https://x.test/p1")
    assert labels(found) == ["Real Title", "Second", "Third", "Fourth"]


def test_a_container_with_no_heading_inside_still_names_its_chapter(chapters):
    archive = ('<div class="chapter">Arc One <a href="p1">go</a></div>'
               '<div class="chapter">Arc Two <a href="p2">go</a></div>'
               '<div class="chapter">Arc Three <a href="p3">go</a></div>'
               '<div class="chapter">Arc Four <a href="p4">go</a></div>')
    found, links = read(chapters, archive, "https://x.test/a.html", "https://x.test/p1")
    assert labels(found) == ["Arc One go", "Arc Two go", "Arc Three go", "Arc Four go"]


def test_a_heading_followed_by_its_links_reads_as_before(chapters):
    archive = ("<h2>Chapter One</h2><a href='p1'>1</a><a href='p2'>2</a>"
               "<h2>Chapter Two</h2><a href='p3'>3</a><a href='p4'>4</a>")
    found, links = read(chapters, archive, "https://x.test/a.html", "https://x.test/p1")
    assert [(c["label"], c["pages"]) for c in found] == [("Chapter One", 2), ("Chapter Two", 2)]


def test_a_page_count_is_only_stripped_when_it_is_a_page_count(chapters):
    assert chapters.heading_says("3. A Snowy Day (4 pages, 5/8/06)") == ("3. A Snowy Day", 4)
    assert chapters.heading_says("Intermission: A Letter (1 page, 4/1/14)") == ("Intermission: A Letter", 1)
    #a title that merely has brackets, or ends in a year, is left alone
    assert chapters.heading_says("The Toy Box (tm)") == ("The Toy Box (tm)", None)
    assert chapters.heading_says("Halloween (2023)") == ("Halloween (2023)", None)


def test_an_archive_that_is_a_dropdown_with_values_from_the_site_root(chapters):
    #every page is an <option> whose value the site's script navigates to, and the chapter starts are
    #links inside a div whose class says "storyline"
    archive = ('<h1>Archive</h1><select>'
               + "".join('<option value="comic/page-{0}">a date - Page {0}</option>'.format(n)
                         for n in range(1, 13))
               + '</select>'
               + "".join('<div class="cc-storyline-header"><a href="https://x.test/comic/page-{0}">'
                         'Book {1}</a></div>'.format(n, at + 1) for at, n in enumerate((1, 5, 9))))
    found, links = read(chapters, archive, "https://x.test/comic/archive", "https://x.test/comic/page-1")
    assert len(links) == 12, "the dropdown's pages are found"
    assert not any("comic/comic" in one for one in links), \
        "and not doubled up by the join: {0}".format([one for one in links if "comic/comic" in one][:3])
    assert labels(found) == ["Book 1", "Book 2", "Book 3"], "three chapters, from the storyline headers"
    assert found[0]["label"] == "Book 1", "the first is named by its own link, not by the page banner"
    assert [c["start_page"] for c in found] == [1, 5, 9]
    assert sum(c["pages"] for c in found) == 12, "every page lands in a chapter"
