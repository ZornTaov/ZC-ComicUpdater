#a comic with no chapters of its own - a page a day for years - cut into parts of a set size, so no reader
#has to open one archive of thousands of pages. the size is remembered, the part still being published keeps
#its name as it fills, the next part starts on its own once it is full, and changing the size is a change
#that moves archives already written, so it needs --force like any other.
import os
import time
import zipfile

from conftest import read_meta, run, write_index, write_meta

NAME = "Uncompressed/Daily"


def add_pages(chapters, library, folder, upto):
    #the comic as the index and the folder know it, up to page `upto`: every file a different size, so
    #each lines up with its own line of the index
    urls = ["https://example.com/comic/{0}/".format(n) for n in range(1, upto + 1)]
    names = ["{0:04d}.png".format(n) for n in range(1, upto + 1)]
    for at, name in enumerate(names):
        path = folder / name
        if not path.exists():
            path.write_bytes(bytes([at % 251]) * (200 + at))
            stamp = time.time() - (len(names) - at) * 10
            os.utime(str(path), (stamp, stamp))
    write_index(chapters.index_path(str(folder), str(library), None),
                [{"n": at + 1, "url": url, "src": "https://example.com/i/" + names[at], "image": names[at],
                  "bytes": 200 + at} for at, url in enumerate(urls)])
    ch(folder, library, "align")


def daily(chapters, library, pages):
    folder = library / "Uncompressed" / "Daily"
    folder.mkdir()
    #the index named in the history, as a scrape that kept one leaves it
    named = os.path.basename(chapters.index_path(str(folder), str(library), None))
    write_meta(folder, {"schema": 2, "settings": {"url": "https://example.com/comic/1/", "output": NAME,
                                     "cbz_path": "CBZs/Daily.cbz"}, "history": {"index_cache": named}})
    add_pages(chapters, library, folder, pages)
    return folder


def ch(folder, library, command, *more):
    done = run("chapters.py", command, folder, "--root", library, *more)
    return done.returncode, done.stdout + done.stderr


def parts(folder):
    return [(c["start_page"], c["end_page"], c["label"]) for c in read_meta(folder)["chapters"]["list"]]


def test_a_comic_is_cut_into_parts_of_the_size_asked(library, chapters):
    folder = daily(chapters, library, 10)
    code, out = ch(folder, library, "chapters", "--every", "4", "--save")
    assert code == 0, out
    #the last part is named for the pages it will hold, not the two it holds so far
    assert parts(folder) == [(1, 4, "Pages 1-4"), (5, 8, "Pages 5-8"), (9, 10, "Pages 9-12")], parts(folder)
    block = read_meta(folder)["chapters"]
    assert block["source"] == "every" and block["every"] == 4, block


def test_the_size_is_remembered_and_the_last_part_fills_under_its_own_name(library, chapters):
    folder = daily(chapters, library, 10)
    ch(folder, library, "chapters", "--every", "4", "--save")
    code, out = ch(folder, library, "chapters", "--save")
    assert code == 0 and "as it remembers" in out and "the same chapters as before" in out, out
    #the comic publishes five more pages: the third part fills, and a fourth begins
    add_pages(chapters, library, folder, 15)
    code, out = ch(folder, library, "chapters", "--save")
    assert code == 0 and "more than before" in out and "WARNING" not in out, out
    assert parts(folder) == [(1, 4, "Pages 1-4"), (5, 8, "Pages 5-8"), (9, 12, "Pages 9-12"),
                             (13, 15, "Pages 13-16")], parts(folder)


def test_a_comic_smaller_than_one_part_is_still_saved(library, chapters):
    #not a page with no chapter headings, which is what one chapter usually means: just a part not yet full
    folder = daily(chapters, library, 3)
    code, out = ch(folder, library, "chapters", "--every", "100", "--save")
    assert code == 0, out
    assert parts(folder) == [(1, 3, "Pages 1-100")], parts(folder)


def test_changing_the_size_moves_written_archives_so_needs_force(library, chapters):
    folder = daily(chapters, library, 10)
    ch(folder, library, "chapters", "--every", "4", "--save")
    code, out = ch(folder, library, "chapters", "--every", "5", "--save")
    assert code == 1 and "--force" in out, out
    assert read_meta(folder)["chapters"]["every"] == 4
    code, out = ch(folder, library, "chapters", "--every", "5", "--save", "--force")
    assert code == 0, out
    assert parts(folder) == [(1, 5, "Pages 1-5"), (6, 10, "Pages 6-10")], parts(folder)
    assert read_meta(folder)["chapters"]["every"] == 5


def test_a_size_below_one_is_refused(library, chapters):
    folder = daily(chapters, library, 10)
    code, out = ch(folder, library, "chapters", "--every", "0", "--save")
    assert code == 2 and "1 or more" in out, out
    assert not read_meta(folder).get("chapters")


def test_each_part_is_packed_into_an_archive_of_its_own(library, chapters):
    folder = daily(chapters, library, 10)
    ch(folder, library, "chapters", "--every", "4", "--save")
    code, out = ch(folder, library, "pack")
    assert code == 0, out
    shelf = library / "CBZs" / "Daily"
    made = sorted(os.listdir(str(shelf)))
    assert made == ["Daily - c001 - Pages 1-4.cbz", "Daily - c002 - Pages 5-8.cbz",
                    "Daily - c003 - Pages 9-12.cbz"], made
    held = []
    for name in made:
        with zipfile.ZipFile(str(shelf / name)) as zf:
            held.append(len([n for n in zf.namelist() if n.endswith(".png")]))
    assert held == [4, 4, 2], held


def unwalked(library, names, name="Numbered"):
    #a comic scraped long before anything recorded which page is which: only its files
    folder = library / "Uncompressed" / name
    folder.mkdir()
    for at, file in enumerate(names):
        (folder / file).write_bytes(bytes([at % 251]) * (200 + at))
    write_meta(folder, {"schema": 2, "settings": {"url": "https://example.com/comic/9/",
                                                  "output": "Uncompressed/" + name,
                                                  "cbz_path": "CBZs/{0}.cbz".format(name)}, "history": {}})
    return folder


def test_a_comic_never_walked_is_cut_by_the_numbers_its_files_carry(library, chapters):
    #named by the site as it numbers its pages, with a second extension an older scrape added, and a page
    #the site lost: 7 is missing, and the part it would be in is simply one page short
    names = ["{0}.png.png".format(n) for n in range(1, 11) if n != 7]
    folder = unwalked(library, names)
    code, out = ch(folder, library, "chapters", "--every", "4", "--save")
    assert code == 0 and "from their numbers" in out, out
    assert parts(folder) == [(1, 4, "Pages 1-4"), (5, 8, "Pages 5-8"), (9, 10, "Pages 9-12")], parts(folder)
    code, out = ch(folder, library, "pack")
    assert code == 0, out
    shelf = library / "CBZs" / "Numbered"
    held = {}
    for name in sorted(os.listdir(str(shelf))):
        with zipfile.ZipFile(str(shelf / name)) as zf:
            held[name] = len([n for n in zf.namelist() if n.endswith(".png")])
    assert list(held.values()) == [4, 3, 2], held


def test_a_comic_kept_from_part_way_has_no_empty_parts_before_its_first_page(library, chapters):
    #numbered by a scrape that began at page 9, as --prefix numbers them
    folder = unwalked(library, ["{0:04d}_strip.png".format(n) for n in range(9, 15)])
    code, out = ch(folder, library, "chapters", "--every", "4", "--save")
    assert code == 0, out
    assert parts(folder) == [(9, 12, "Pages 9-12"), (13, 14, "Pages 13-16")], parts(folder)


def test_filenames_that_do_not_say_which_page_is_which_are_not_guessed_at(library, chapters):
    folder = unwalked(library, ["1.png", "2.png", "cover.png"])
    code, out = ch(folder, library, "chapters", "--every", "4", "--save")
    assert code == 2 and "carry no page number" in out and "chapters.py index" in out, out
    folder = unwalked(library, ["1.png", "2.png", "2.gif"], "Twice")
    code, out = ch(folder, library, "chapters", "--every", "4", "--save")
    assert code == 2 and "more than one file" in out, out
    assert not read_meta(folder).get("chapters")


def test_the_editor_cuts_a_numbered_comic_without_walking_it(library, chapters, web):
    #no site is running at all: a walk would have nothing to walk
    folder = unwalked(library, ["{0:04d}.png".format(n) for n in range(1, 11)])
    page = web()
    code, answer = page.call("/api/chapterize", {"name": "Uncompressed/Numbered", "every": "4"})
    assert code == 200 and answer.get("numbers_first") is True and answer.get("walking") is False, answer
    assert page.wait_idle(300), "the parts were never worked out"
    assert "without walking" in page.said(), page.said()[-600:]
    assert [start for start, _, _ in parts(folder)] == [1, 5, 9], page.said()[-600:]
    assert sorted(os.listdir(str(library / "CBZs" / "Numbered"))) == [
        "Numbered - c001 - Pages 1-4.cbz", "Numbered - c002 - Pages 5-8.cbz", "Numbered - c003 - Pages 9-12.cbz"]


def test_the_editor_sets_the_size_and_works_the_parts_out(library, chapters, web):
    folder = daily(chapters, library, 10)
    page = web()
    _, detail = page.call("/api/comic?name=" + NAME)
    #one source or the other: both would each save over the other's chapters on every run
    code, answer = page.call("/api/settings", {"name": NAME, "settings": {
        "chapters_url": "https://example.com/archive", "chapters_every": "4"}})
    assert code == 400 and "not both" in answer.get("error", ""), answer
    assert page.call("/api/settings", {"name": NAME, "settings": {"chapters_every": "four"}})[0] == 400

    code, answer = page.call("/api/settings", {"name": NAME, "updated": detail["updated"],
                                               "settings": {"chapters_url": "", "chapters_every": "4"}})
    assert code == 200 and answer.get("saved") and "chapters_every" in answer["changed"], answer
    block = read_meta(folder)["chapters"]
    assert block["source"] == "every" and block["every"] == 4, block

    code, answer = page.call("/api/chapterize", {"name": NAME, "every": "4"})
    assert code == 200 and answer.get("from") == "every" and answer.get("walking") is False, answer
    assert page.wait_idle(300), "the parts were never worked out"
    assert [start for start, _, _ in parts(folder)] == [1, 5, 9], parts(folder)
    assert len(os.listdir(str(library / "CBZs" / "Daily"))) == 3
    _, detail = page.call("/api/comic?name=" + NAME)
    assert detail["chapters"]["every"] == 4 and detail["chapters"]["count"] == 3, detail["chapters"]
