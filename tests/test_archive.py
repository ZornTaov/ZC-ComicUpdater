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


def read_walked(chapters, html, base, walk):
    #what a real run does: the archive read against the pages a walk recorded, in the walk's order
    reader = chapters.ArchiveReader()
    reader.feed(html)
    pages = [{"n": n, "url": url} for n, url in enumerate(walk, 1)]
    found, listed = chapters.chapters_from_events(reader.events, chapters.first_of_each(pages), base)
    return chapters.settle_chapters(found, pages)


#a site that names each chapter only as a link to a page listing that chapter, with the chapter's first and
#last pages linked under it, and a bonus section in the same folder at the bottom
SPANS = ((1, 6), (7, 17), (18, 18), (19, 30))
LISTED = ("".join('<p><a href="Comics/List_{0:03d}.php">Chapter {0}: Title {0}</a><br>Comics: '
                  '<a href="Comics/Page_{1:03d}.php">#{1}</a>{2}</p><p>A summary of chapter {0}.</p>'
                  .format(at, first, "" if first == last else
                          ' through <a href="Comics/Page_{0:03d}.php">#{0}</a>'.format(last))
                  for at, (first, last) in enumerate(SPANS, 1))
          + '<p><a href="Comics/List_Bonus.php">Bonus Comics</a><br>Guest art and the like.</p>')


def test_a_chapter_named_only_by_its_link_to_a_list_of_its_pages(chapters):
    walk = ["https://x.test/Comics/Page_{0:03d}.php".format(n) for n in range(1, 31)]
    found = read_walked(chapters, LISTED, "https://x.test/arch.php", walk)
    assert labels(found) == ["Chapter {0}: Title {0}".format(n) for n in range(1, 5)], \
        "each chapter is named by its link, though the link is not a page of the comic"
    assert [c["start_page"] for c in found] == [1, 7, 18, 19]
    assert [c["pages"] for c in found] == [6, 11, 1, 12], "the walk fills in the pages between"


def test_a_preview_leaves_out_the_pages_that_list_chapters(chapters):
    found, links = read(chapters, LISTED, "https://x.test/arch.php", "https://x.test/Comics/Page_001.php")
    assert not any("List_" in one for one in links), \
        "a chapter's list, or the bonus section's, sits beside the pages but is not one: {0}".format(links)
    assert len(found) == 4, labels(found)


def storyline(name, pages, url="https://x.test/strip/{0}"):
    #a box per storyline: a thumbnail linking to its first page, its name linking there too, then every page
    return ('<div class="cc-storyline-contain"><div class="cc-storyline-thumb"><a href="{0}"><img src="t.jpg">'
            '</a></div><div class="cc-storyline-text"><div class="cc-storyline-header"><a href="{0}">{1}</a>'
            '</div><div class="cc-storyline-pagetitles">{2}</div></div></div>'
            .format(url.format(pages[0]), name,
                    "".join('<div class="cc-pagerow"><a href="{0}">{1}</a></div>'.format(url.format(n), n)
                            for n in pages)))


#three books in order, with the filler pages published among them listed apart at the bottom
BOOKS = {"Book #1": [1, 2, 3, 5, 6], "Book #2": [7, 8, 10, 11], "Book #3": [12, 13, 14, 16]}
FILLERS = [4, 9, 15]
BOXED = ('<h1>Latest Page</h1><p>Read it <a href="https://x.test/strip">here!</a></p><h1>Archive</h1>'
         + "".join(storyline(name, pages) for name, pages in BOOKS.items()) + storyline("Fillers", FILLERS))


def test_a_storyline_box_makes_one_chapter_named_by_its_header(chapters):
    found, links = read(chapters, BOXED, "https://x.test/strip/archive", "https://x.test/strip/1")
    assert labels(found)[:3] == ["Book #1", "Book #2", "Book #3"], \
        "no chapter one page long named for its first page's row, and none named for the page banner"
    assert "https://x.test/strip" not in links, "the comic's front page shows the newest page, not a page"


def test_fillers_listed_apart_stay_where_they_were_published(chapters):
    walk = ["https://x.test/strip/{0}".format(n) for n in range(1, 17)]
    found = read_walked(chapters, BOXED, "https://x.test/strip/archive", walk)
    assert labels(found) == ["Book #1", "Book #2", "Book #3"], "the fillers are not a chapter"
    assert [(c["start_page"], c["end_page"]) for c in found] == [(1, 6), (7, 11), (12, 16)], \
        "each filler stays inside the book it was published in, so the archives read as the site does"


def test_a_walked_comic_with_no_address_of_its_own_is_previewed_by_its_walk(chapters, library, monkeypatch,
                                                                            capsys):
    #an ended comic adopted from an archive keeps no address in its settings; its walk has one for every page
    import argparse

    from comiclib.chapters import chapterlist
    from conftest import write_index, write_meta
    folder = library / "Uncompressed" / "Boxed"
    write_meta(folder, {"schema": 2, "settings": {"ended": True}})
    write_index(chapters.index_path(str(folder), str(library), None),
                [{"n": n, "url": "https://x.test/strip/{0}".format(n)} for n in range(1, 17)])
    monkeypatch.setattr(chapterlist, "read_archive", lambda *given: BOXED)
    asked = argparse.Namespace(archive="https://x.test/strip/archive", like=None, browser=False, script=None,
                               root=str(library), cache=None)
    assert chapterlist.try_archive(str(folder), asked) == 0
    said = capsys.readouterr().out
    assert "read against the 16 page(s) this comic's walk recorded" in said, said
    assert "chapters it would read: 3" in said, "the books, and no chapter of fillers\n" + said


#a site whose archive lists only its chapters, each heading leading to a page of the site's own that lists
#that chapter's pages, oldest first, with the newest page of the comic in a sidebar on every page
SITE = "https://x.test"
#S is a page of specials published in among the chapters, not a chapter of its own
LISTED_ELSEWHERE = {"A": range(1, 6), "B": range(6, 11), "D": range(16, 21), "S": (3, 8, 13)}


def chapter_box(slug, name):
    return ('<a href="/chapter/{0}/"><img src="/t/{0}.jpg"></a><div class="chapter-title">{1}</div>'
            '<a href="/">Site.com</a><a href="/chapter/{0}/">READ THIS CHAPTER</a>'.format(slug, name))


CHAPTER_LIST = ('<h1>Some Comic</h1><a href="/about/">About</a><a href="/chapter/extras/">Extras</a>'
                '<a href="/store/">Store</a><h2>Archives</h2><h2>Web Comics</h2>'
                + chapter_box("a", "A") + chapter_box("b", "B")
                #one chapter linking straight to its first page, as some on such a site do
                + '<a href="/comic/e11/"><img src="/t/c.jpg"></a><div class="chapter-title">C</div>'
                  '<a href="/comic/e11/">READ THIS CHAPTER</a>'
                + chapter_box("d", "D")
                #a story told off the main run of next links, linked straight to its own page, which a walk
                #never reaches - reading it would find only its buttons, the first-page one among them
                + '<a href="/comic/side-story/"><img src="/t/x.jpg"></a><div class="chapter-title">Side</div>'
                  '<a href="/comic/side-story/">READ THIS CHAPTER</a>'
                + '<h2>Specials</h2>' + chapter_box("s", "S")
                + '<h2>Books</h2><a href="/2020/01/one/">One</a><a href="/2020/02/two/">Two</a><a href="#">x</a>')


def chapter_page(url):
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    held = LISTED_ELSEWHERE.get(slug.upper())
    if held is None:
        raise AssertionError("fetched {0}, which no chapter heading leads to".format(url))
    return ("".join('<a href="/comic/e{0}/">Episode {0}</a>'.format(n) for n in held)
            + '<div class="sidebar"><a href="/comic/e20/">The newest page</a></div>')


def test_a_heading_leading_to_a_page_of_its_chapter_has_that_page_read(chapters):
    #the walk ended by stepping onto the site's front page, which every "home" link and "#" leads to
    walk = [{"n": n, "url": "{0}/comic/e{1}/".format(SITE, n)} for n in range(1, 21)] + [
        {"n": 21, "url": SITE + "/"}]
    reader = chapters.ArchiveReader()
    reader.feed(CHAPTER_LIST)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return chapter_page(url)

    found, _ = chapters.chapters_from_events(reader.events, chapters.first_of_each(walk), SITE + "/archives/",
                                             fetch=fetch)
    found = chapters.settle_chapters(found, walk)
    assert [(c["label"], c["start_page"]) for c in found] == [("A", 1), ("B", 6), ("C", 11), ("D", 16)], \
        "each named by its own heading - not the archive's title above the first - and started where its " \
        "own page says, not at the newest page in the sidebar"
    assert sorted(fetched) == [SITE + "/chapter/{0}/".format(slug) for slug in ("a", "b", "d", "s")], \
        "only the chapters' own pages: not the menu, not the posts, not one a heading already links into, " \
        "and not a page of the comic the walk never reached"


def test_an_archive_that_lists_its_pages_never_fetches_anything(chapters):
    walk = [{"n": n, "url": "https://x.test/strip/{0}".format(n)} for n in range(1, 17)]
    reader = chapters.ArchiveReader()
    reader.feed(BOXED)

    def fetch(url):
        raise AssertionError("fetched {0} for an archive that lists every page".format(url))

    found, _ = chapters.chapters_from_events(reader.events, chapters.first_of_each(walk),
                                             "https://x.test/strip/archive", fetch=fetch)
    assert [c["label"] for c in chapters.settle_chapters(found, walk)] == ["Book #1", "Book #2", "Book #3"]


#an archive that nests its storylines inside books: a book is a heading of its own, with no link, straight
#above the first storyline in it - and the storylines' numbers start again in each book
NESTED = ('<h1>Archive</h1><select>' + "".join('<option value="strip/{0}">Page {0}</option>'.format(n)
                                               for n in range(1, 13)) + '</select>'
          + '<div class="cc-storyline-contain"><div class="cc-storyline-header">Book 1 - The Start</div></div>'
          + storyline("01 - Opening", [1, 2, 3]) + storyline("02 - Trouble", [4, 5])
          + '<div class="cc-storyline-contain"><div class="cc-storyline-header">Book 2</div></div>'
          + storyline("01 - Return", [6, 7, 8]) + storyline("02 - Ending", [9, 10, 11, 12]))


def test_a_nested_archive_is_cut_by_its_books_when_asked(chapters):
    walk = [{"n": n, "url": "https://x.test/strip/{0}".format(n)} for n in range(1, 13)]

    def cut(outer):
        reader = chapters.ArchiveReader()
        reader.feed(NESTED)
        found, _ = chapters.chapters_from_events(reader.events, chapters.first_of_each(walk),
                                                 "https://x.test/strip/archive", outer=outer)
        return [(c["label"], c["start_page"], c["pages"]) for c in chapters.settle_chapters(found, walk)]

    assert cut(False) == [("01 - Opening", 1, 3), ("02 - Trouble", 4, 2), ("01 - Return", 6, 3),
                          ("02 - Ending", 9, 4)], "every storyline, as before"
    assert cut(True) == [("Book 1 - The Start", 1, 5), ("Book 2", 6, 7)], \
        "one per book, named by the book, holding every storyline in it"


def test_a_link_names_a_chapter_only_when_its_words_are_a_chapter_and_a_number(chapters):
    for named in ("Chapter 2: The Long Way Round", "Book #3", "Vol. 4", "Episode 12", "Arc 1 - Beginnings"):
        assert chapters.names_a_chapter(named), named
    for not_named in ("Chapters", "Chapter 3 Page 4", "Bonus Comics", "#12", "Partners", "Fillers"):
        assert not chapters.names_a_chapter(not_named), not_named


def test_a_chapter_starting_on_a_page_of_several_images_starts_at_the_first(chapters):
    pages = [{"n": 1, "url": "https://x.test/p1"}, {"n": 2, "url": "https://x.test/p2"},
             {"n": 3, "url": "https://x.test/p2"}, {"n": 4, "url": "https://x.test/p3"}]
    assert chapters.first_of_each(pages)["x.test/p2"] == 2, "not the page's last image"


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
