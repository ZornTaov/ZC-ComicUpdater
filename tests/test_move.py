#a comic moved to another folder of the library - in under its author's - with everything that says where
#it lives moved alongside: the archive or chapter archives on the CBZs shelf, the settings naming them, and
#the index, whose name is made from where the comic was. a move that cannot be made whole is refused before
#anything is touched, and one that fails part way puts back what it had done.
import os
import zipfile

import pytest

from comiclib import metadata, moving
from comiclib.chapters.index import index_path
from conftest import open_page, read_meta, wait_until, write_index, write_meta

URL = "https://example.com/comic/1/"


def comic(library, where="MyComic", archive="CBZs/MyComic.cbz", pages=3, **extra):
    #pages under Uncompressed, and the single archive where the settings say, as a scrape leaves them
    folder = library / "Uncompressed" / where
    folder.mkdir(parents=True)
    for n in range(1, pages + 1):
        (folder / "{0:04d}.png".format(n)).write_bytes(bytes([n]) * 100)
    settings = {"url": URL, "output": "Uncompressed/" + where.replace(os.sep, "/"), "cbz_path": archive}
    write_meta(folder, dict({"schema": 2, "settings": settings, "history": {}}, **extra))
    if archive:
        full = library / archive
        full.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(full), "w") as zf:
            zf.writestr("0001.png", b"x")
    return folder


def walked(folder, library):
    #a record of which page is which, named the way a walk names it from where the comic is now
    cache = index_path(str(folder), str(library))
    write_index(cache, [{"n": 1, "url": URL}])
    return cache


def move(folder, library, into):
    planned = moving.plan(str(folder), str(library), into)
    return moving.carry_out(planned)


def test_a_comic_and_its_archive_move_in_under_an_author(library):
    folder = comic(library)
    cache = walked(folder, library)
    move(folder, library, "Uncompressed/SomeAuthor")
    now = library / "Uncompressed" / "SomeAuthor" / "MyComic"
    assert not folder.exists() and sorted(os.listdir(str(now)))[:3] == ["0001.png", "0002.png", "0003.png"]
    assert not (library / "CBZs" / "MyComic.cbz").exists()
    assert (library / "CBZs" / "SomeAuthor" / "MyComic.cbz").is_file()
    meta = read_meta(now)
    assert meta["settings"]["cbz_path"] == "CBZs/SomeAuthor/MyComic.cbz", meta["settings"]
    assert meta["settings"]["output"] == "Uncompressed/SomeAuthor/MyComic", meta["settings"]
    #the index stays where it is under its old name, and the comic says which it is, so it is still found
    assert os.path.exists(cache)
    assert meta["history"]["index_cache"] == os.path.basename(cache)
    assert index_path(str(now), str(library)) == cache
    #and the move is among the edits, which is how the editor shows where the comic came from
    assert meta["history"]["edits"][-1]["changed"]["folder"] == ["Uncompressed/MyComic",
                                                                  "Uncompressed/SomeAuthor/MyComic"]


def test_every_rename_is_written_down_for_the_reader(library):
    #the reader keeps a comic's place and cover by where it is, and finds them again from this record
    folder = comic(library)
    (library / "CBZs" / "MyComic.png").write_bytes(b"cover")
    move(folder, library, "Uncompressed/SomeAuthor")
    #the cover beside the archive went with it, rather than staying as the cover of nothing
    assert (library / "CBZs" / "SomeAuthor" / "MyComic.png").read_bytes() == b"cover"
    meta = read_meta(library / "Uncompressed" / "SomeAuthor" / "MyComic")
    assert metadata.moves(meta) == [[
        {"what": "archive", "from": "CBZs/MyComic.cbz", "to": "CBZs/SomeAuthor/MyComic.cbz"},
        {"what": "cover", "from": "CBZs/MyComic.png", "to": "CBZs/SomeAuthor/MyComic.png"},
        {"what": "pages", "from": "Uncompressed/MyComic", "to": "Uncompressed/SomeAuthor/MyComic"}]]
    records = metadata.moves(meta)
    assert metadata.before_moves("Uncompressed/SomeAuthor/MyComic", records) == ["Uncompressed/MyComic"]
    assert metadata.after_moves("CBZs/MyComic.png", records) == "CBZs/SomeAuthor/MyComic.png"
    assert metadata.before_moves("CBZs/Unrelated.cbz", records) == []


def test_chapter_archives_move_as_a_folder_and_their_record_follows(library):
    folder = comic(library, archive=None, chapters={"folder": "CBZs/MyComic", "list": [
        {"number": 1, "label": "One", "start_page": 1, "end_page": 3}]})
    shelf = library / "CBZs" / "MyComic"
    shelf.mkdir()
    (shelf / "MyComic - c001 - One.cbz").write_bytes(b"zip")
    move(folder, library, "Uncompressed/SomeAuthor")
    moved = library / "CBZs" / "SomeAuthor" / "MyComic"
    assert (moved / "MyComic - c001 - One.cbz").is_file() and not shelf.exists()
    meta = read_meta(library / "Uncompressed" / "SomeAuthor" / "MyComic")
    assert meta["chapters"]["folder"] == "CBZs/SomeAuthor/MyComic", meta["chapters"]


def test_an_archive_the_shelf_rule_found_is_still_found_by_it(library):
    #no cbz_path: the archive is wherever the rule puts it, and after the move the rule puts it at the new place
    folder = comic(library, archive=None)
    with zipfile.ZipFile(str(library / "CBZs" / "MyComic.cbz"), "w") as zf:
        zf.writestr("0001.png", b"x")
    move(folder, library, "Uncompressed/SomeAuthor")
    assert (library / "CBZs" / "SomeAuthor" / "MyComic.cbz").is_file()
    assert read_meta(library / "Uncompressed" / "SomeAuthor" / "MyComic")["settings"]["cbz_path"] is None


def test_moving_out_of_an_author_takes_away_the_folders_left_empty(library):
    folder = comic(library, where=os.path.join("OldAuthor", "MyComic"), archive="CBZs/OldAuthor/MyComic.cbz")
    #another comic's folder beside it keeps the shelf's matching folder in use
    other = comic(library, where=os.path.join("Busy", "Theirs"), archive="CBZs/Busy/Theirs.cbz")
    move(folder, library, "Uncompressed")
    assert (library / "Uncompressed" / "MyComic").is_dir() and (library / "CBZs" / "MyComic.cbz").is_file()
    assert not (library / "Uncompressed" / "OldAuthor").exists() and not (library / "CBZs" / "OldAuthor").exists()
    #the shelves themselves are never taken away, and nor is anything still holding a comic
    assert (library / "CBZs").is_dir() and other.is_dir()


def test_an_archive_filed_somewhere_of_its_own_stays_and_is_said_to(library):
    folder = comic(library, archive="CBZs/Collected/Everything.cbz")
    planned = moving.plan(str(folder), str(library), "Uncompressed/SomeAuthor")
    assert [stays for _, stays in moving.describe(planned)] == [False, True], moving.describe(planned)
    moving.carry_out(planned)
    assert (library / "CBZs" / "Collected" / "Everything.cbz").is_file()
    meta = read_meta(library / "Uncompressed" / "SomeAuthor" / "MyComic")
    assert meta["settings"]["cbz_path"] == "CBZs/Collected/Everything.cbz"


def test_a_chapter_folder_not_named_after_the_comic_is_never_moved(library):
    #a folder of chapters recorded as an author's would take every other comic in it along
    folder = comic(library, archive=None, chapters={"folder": "CBZs", "list": [{"number": 1}]})
    planned = moving.plan(str(folder), str(library), "Uncompressed/SomeAuthor")
    assert [what for _, _, what in planned["moves"]] == ["pages"], planned["moves"]


@pytest.mark.parametrize("into, why", [
    ("Uncompressed", "already"),
    ("../Elsewhere", "inside the library"),
    ("C:/Elsewhere", "inside the library"),
    ("Uncompressed/MyComic/Inside", "its own folder"),
    ("Uncompressed/Theirs", "comic of its own"),
    ("Uncompressed/Taken", "already there"),
])
def test_a_move_that_cannot_be_made_whole_is_refused_untouched(library, into, why):
    folder = comic(library)
    comic(library, where="Theirs", archive=None)
    (library / "Uncompressed" / "Taken" / "MyComic").mkdir(parents=True)
    with pytest.raises(moving.Refused) as refused:
        moving.plan(str(folder), str(library), into)
    assert why in str(refused.value), str(refused.value)
    assert (folder / "0001.png").exists() and (library / "CBZs" / "MyComic.cbz").exists()


def test_an_archive_in_the_way_is_refused_before_the_pages_go(library):
    folder = comic(library)
    (library / "CBZs" / "SomeAuthor").mkdir()
    (library / "CBZs" / "SomeAuthor" / "MyComic.cbz").write_bytes(b"another")
    with pytest.raises(moving.Refused, match="already there"):
        moving.plan(str(folder), str(library), "Uncompressed/SomeAuthor")


def test_a_move_that_fails_part_way_puts_back_what_it_had_done(library, monkeypatch):
    folder = comic(library)
    planned = moving.plan(str(folder), str(library), "Uncompressed/SomeAuthor")
    real = os.rename

    def held_open(source, target):
        #the pages folder will not go - something has it open - after the archive already has
        if os.path.basename(str(source)) == "MyComic":
            raise PermissionError("in use")
        return real(source, target)

    monkeypatch.setattr(moving.os, "rename", held_open)
    with pytest.raises(moving.Refused, match="put back"):
        moving.carry_out(planned)
    assert (library / "CBZs" / "MyComic.cbz").is_file() and (folder / "0001.png").exists()
    assert not (library / "CBZs" / "SomeAuthor").exists() and not (library / "Uncompressed" / "SomeAuthor").exists()
    assert read_meta(folder)["settings"]["cbz_path"] == "CBZs/MyComic.cbz"


def test_the_places_offered_are_every_folder_a_comic_could_go_in(library):
    comic(library)
    #an author's folder with nothing tracked in it yet is the very place a comic is moved to
    (library / "Uncompressed" / "SomeAuthor").mkdir()
    (library / "Uncompressed" / "SomeAuthor" / "Series").mkdir()
    #pages nobody has adopted yet are a comic, not a place to put one
    (library / "Uncompressed" / "Loose").mkdir()
    (library / "Uncompressed" / "Loose" / "0001.png").write_bytes(b"x")
    (library / "Uncompressed" / ".uploads").mkdir()
    deep = library / "Uncompressed" / "A" / "B" / "C" / "D"
    deep.mkdir(parents=True)
    assert moving.places(str(library), "Uncompressed", 5) == [
        "Uncompressed", "Uncompressed/A", "Uncompressed/A/B", "Uncompressed/A/B/C",
        "Uncompressed/SomeAuthor", "Uncompressed/SomeAuthor/Series"]
    #a comic in D would be six deep, past the five searched, so D is not offered
    assert moving.places(str(library), "Uncompressed", 3) == [
        "Uncompressed", "Uncompressed/A", "Uncompressed/SomeAuthor"]
    assert moving.places(str(library), "Nowhere", 5) == []


def test_an_author_filed_only_on_the_shelf_is_offered_as_a_pages_folder(library):
    #the author's archives are on the shelf by author, but no comic of theirs has its pages here yet
    comic(library)
    author = library / "CBZs" / "SomeAuthor"
    author.mkdir()
    (author / "AnotherComic.cbz").write_bytes(b"zip")
    (author / "cover.jpg").write_bytes(b"jpg")
    #a comic's own folder of chapter archives, and of its one archive, are comics, not places
    (library / "CBZs" / "Chaptered").mkdir()
    (library / "CBZs" / "Chaptered" / "Chaptered - c001 - One.cbz").write_bytes(b"zip")
    (author / "Kept").mkdir()
    (author / "Kept" / "Kept.cbz").write_bytes(b"zip")
    #and a shelf folder matching a tracked comic is that comic
    (library / "CBZs" / "MyComic").mkdir()
    assert moving.places(str(library), "Uncompressed", 5, "CBZs") == ["Uncompressed", "Uncompressed/SomeAuthor"]
    #without the shelf it is not known of at all, which was the trouble
    assert moving.places(str(library), "Uncompressed", 5) == ["Uncompressed"]


def test_the_page_shows_a_move_then_queues_it(library, web):
    folder = comic(library)
    (library / "Uncompressed" / "SomeAuthor").mkdir()
    (library / "CBZs" / "ShelvedAuthor").mkdir()
    page = web()
    code, offered = page.call("/api/places")
    assert code == 200 and offered["places"] == [
        "Uncompressed", "Uncompressed/ShelvedAuthor", "Uncompressed/SomeAuthor"], offered
    code, shown = page.call("/api/move", {"name": "Uncompressed/MyComic", "into": "Uncompressed/SomeAuthor",
                                          "dry_run": True})
    assert code == 200 and shown["to"] == "Uncompressed/SomeAuthor/MyComic", shown
    assert [line["text"].split(":")[0] for line in shown["lines"]] == ["archive", "pages"], shown
    assert folder.exists(), "looking moved it"
    code, refused = page.call("/api/move", {"name": "Uncompressed/MyComic", "into": "../Out"})
    assert code == 400 and "inside the library" in refused["error"], refused

    code, queued = page.call("/api/move", {"name": "Uncompressed/MyComic", "into": "Uncompressed/SomeAuthor"})
    assert code == 200 and queued["label"] == "Move Uncompressed/MyComic", queued
    assert page.wait_idle(60)
    _, state = page.call("/api/state")
    done = next(entry for entry in state["history"] if entry["id"] == queued["queued"])
    assert not done["error"] and done["outcome"] == "now Uncompressed/SomeAuthor/MyComic", done
    assert page.call("/api/comic?name=Uncompressed/MyComic")[0] == 404
    code, detail = page.call("/api/comic?name=Uncompressed/SomeAuthor/MyComic")
    assert code == 200 and detail["settings"]["cbz_path"] == "CBZs/SomeAuthor/MyComic.cbz", detail


@pytest.mark.browser
def test_the_editor_moves_a_comic(library, web, browser):
    comic(library)
    comic(library, where=os.path.join("SomeAuthor", "Theirs"), archive=None)
    (library / "Uncompressed" / "Untracked Author").mkdir()
    page = web()
    open_page(browser, page.base + "/")
    edit = "document.querySelector('[data-edit=\"Uncompressed/MyComic\"]')"
    wait_until(lambda: browser.execute_script("return " + edit), why="the comic never listed")
    browser.execute_script(edit + ".click()")
    wait_until(lambda: browser.execute_script("return document.getElementById('editor').open"),
               why="the editor never opened")
    offered = "return [...document.querySelectorAll('#e-move-places option')].map(o => o.value)"
    #the folders other comics sit in are offered at once; a folder holding none yet once the move is opened
    assert "Uncompressed/SomeAuthor" in browser.execute_script(offered)
    browser.execute_script("document.getElementById('edit-move-box').open = true")
    wait_until(lambda: "Uncompressed/Untracked Author" in browser.execute_script(offered),
               why="a folder with no comic in it was never offered")
    #and the move waits until what it would do has been shown
    assert browser.execute_script("return document.getElementById('e-move-go').disabled")
    browser.execute_script("document.getElementById('e-move-into').value = 'Uncompressed/SomeAuthor';"
                           "document.getElementById('e-move-check').click()")
    wait_until(lambda: not browser.execute_script("return document.getElementById('e-move-go').disabled"),
               why="what would move was never shown")
    assert "CBZs/SomeAuthor/MyComic.cbz" in browser.execute_script(
        "return document.getElementById('e-move-plan').textContent")
    browser.execute_script("document.getElementById('e-move-go').click()")
    wait_until(lambda: (library / "Uncompressed" / "SomeAuthor" / "MyComic" / "mirror_metadata.json").exists(),
               why="the comic never moved")
    assert page.wait_idle(60)
