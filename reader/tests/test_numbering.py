#chapter archives named by the chapter's own number - c391 for a comic begun part way, c012.5 for an
#intermission after chapter 12 - read as the chapters of their comic in the order they read, edited through,
#and a chapter renamed from its place to its number keeping where it was read up to.
import json

import pytest

from conftest import comic_folder, page_names
from test_editing import settle

from comiclib import cbz, comicinfo
from comiclib.chapters.numbering import name_part, numbered

LABELS = ["Chapter 12", "Intermission", "Chapter 13"]


def chaptered(library, name="MyComic", labels=LABELS, by_place=False):
    #two pages a chapter, each archive named as packing names it: by the chapter's own number, or by its
    #place as packing named them before
    folder = comic_folder(library, name, 2 * len(labels))
    names = page_names(folder)
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    metadata["settings"]["output"] = "Uncompressed/" + name
    metadata["chapters"] = {"folder": "CBZs/" + name, "source": "archive", "list": [
        {"number": at, "label": label, "start_page": 2 * at - 1, "end_page": 2 * at} for at, label in enumerate(labels, 1)]}
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    for chapter in numbered(metadata["chapters"]):
        part = "{0:03d}".format(chapter["number"]) if by_place else name_part(chapter["called"])
        cbz.write(str(library / "CBZs" / name / "{0} - c{1} - {2}.cbz".format(name, part, chapter["label"])),
                  str(folder), names[chapter["start_page"] - 1:chapter["end_page"]],
                  about=comicinfo.about_chapter(str(folder), metadata, chapter if not by_place else
                                                dict(chapter, called=None), len(labels)))
    return folder


def parts(app):
    library = app.state.library
    found = [comic for comic in library.comics.values() if comic.get("parent")]
    by_id = {comic["id"]: comic for comic in found}
    first = next(comic for comic in found if library.neighbours[comic["id"]]["previous"] is None)
    order = [first]
    while library.neighbours[order[-1]["id"]]["next"]:
        order.append(by_id[library.neighbours[order[-1]["id"]]["next"]["id"]])
    return order


def test_an_intermission_named_by_its_number_is_a_chapter_read_between_its_neighbours(library, make_app):
    chaptered(library)
    app = make_app()
    order = parts(app)
    assert [(comic["title"], comic["number"]) for comic in order] == [
        ("Chapter 12", "12"), ("Intermission", "12.5"), ("Chapter 13", "13")]
    assert len(app.state.library.comics) == 3, "every archive a chapter of the comic, none a comic of its own"


def test_a_comic_begun_part_way_is_read_from_its_first_chapter_on(library, make_app):
    chaptered(library, labels=["Chapter 391", "Chapter 392"])
    assert [comic["number"] for comic in parts(make_app())] == ["391", "392"]


def test_an_edit_reaches_every_chapter_named_by_its_number(library, client):
    chaptered(library)
    settle(library)
    api, _ = client()
    intermission = next(c for c in api.get("/api/library").json()["comics"] if c["title"] == "Intermission")
    saved = api.put("/api/comics/{0}/info".format(intermission["id"]), json={"info": {"writer": "SomeAuthor"}})
    assert saved.status_code == 200 and saved.json()["told"] == 3, saved.text


def test_a_chapter_renamed_from_its_place_to_its_number_keeps_where_it_was_read_up_to(library, make_app):
    #packing's own renaming, so this is the record the scraper writes. it reads the comic's index rule, which
    #pulls in requests: the reader's image has none, and runs nothing of the scraper's
    pytest.importorskip("requests")
    from comiclib.chapters import packing
    folder = chaptered(library, by_place=True)
    app = make_app()
    store = app.state.store
    old = next(comic for comic in app.state.library.comics.values() if comic["title"] == "Intermission")
    assert old["number"] == "2"
    store.save_progress(old["id"], app.state.library.stream(old)["pages"][1]["key"], 1, 2)
    app.state.library.sources.forget(set())
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    shelf = str(library / "CBZs" / "MyComic")
    planned = packing.renames_to_numbers(str(folder), shelf, numbered(metadata["chapters"]))
    assert len(planned) == 3
    assert packing.rename_to_numbers(str(folder), shelf, planned, str(library))
    app.state.library.scan()
    new = next(comic for comic in app.state.library.comics.values() if comic["title"] == "Intermission")
    assert new["number"] == "12.5" and new["id"] != old["id"]
    assert store.progress(new["id"])["position"] == 1
