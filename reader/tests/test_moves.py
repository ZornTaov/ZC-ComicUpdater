#a comic the scraper moved to another folder - in under its author - read on from where it was left: its
#place, its settings, how it has grown and its cover carried from the id of its old place to the id of its
#new one, which the reader finds from the move the scraper wrote into the comic's metadata. moved here by
#the scraper's own move, so this is tested against exactly the record the scraper writes.
import json
import os

import pytest

from conftest import comic_folder, page_names, png

from comiclib import cbz, comicinfo

#the scraper's move reads the comic's index rule, which pulls in requests: the reader's image has none, and
#runs nothing of the scraper's, but this machine has both
pytest.importorskip("requests")
from comiclib import moving  # noqa: E402


def single(library, name="MyComic"):
    folder = comic_folder(library, name, 4, settings={"cbz_path": "CBZs/{0}.cbz".format(name)})
    cbz.write(str(library / "CBZs" / (name + ".cbz")), str(folder), page_names(folder))
    return folder


def chaptered(library, name="MyComic"):
    folder = comic_folder(library, name, 6)
    names = page_names(folder)
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    metadata["chapters"] = {"folder": "CBZs/" + name, "list": []}
    for number, (start, end) in enumerate([(1, 3), (4, 6)], 1):
        chapter = {"number": number, "label": "Part {0}".format(number), "start_page": start, "end_page": end}
        metadata["chapters"]["list"].append(chapter)
        cbz.write(str(library / "CBZs" / name / "{0} - c{1:03d} - Part {1}.cbz".format(name, number)), str(folder),
                  names[start - 1:end], about=comicinfo.about_chapter(str(folder), metadata, chapter, 2))
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    return folder


def move(folder, root, into):
    moving.carry_out(moving.plan(str(folder), str(root), into))


def by_title(app, title):
    return next(comic for comic in app.state.library.comics.values() if comic["title"] == title)


def test_a_moved_comic_keeps_its_place_settings_growth_and_cover(library, client):
    folder = single(library)
    api, app = client()
    store = app.state.store
    old = by_title(app, "MyComic")
    stream = app.state.library.stream(old)
    store.save_progress(old["id"], stream["pages"][2]["key"], 2, 4, 0.5)
    store.save_settings("comic:" + old["id"], {"direction": "rtl"})
    chosen = api.put("/api/covers", json={"target": "comic:" + old["id"], "comic": old["id"], "page": 1}).json()
    assert chosen["shelf"] == "CBZs/MyComic.png", chosen
    grown = store.growth()[old["id"]]

    #the reader holds a few archives open for turning pages. linux, where both containers run, renames a
    #file held open; windows refuses, and the move puts everything back and says to close the reader
    app.state.library.sources.forget(set())
    move(folder, library, "Uncompressed/SomeAuthor")
    #the cover the reader wrote beside the archive went with it, not left as the cover of nothing
    assert (library / "CBZs" / "SomeAuthor" / "MyComic.png").is_file()
    assert not (library / "CBZs" / "MyComic.png").exists()
    app.state.library.scan()
    new = by_title(app, "MyComic")
    assert new["id"] != old["id"]
    kept = store.progress(new["id"])
    assert (kept["key"], kept["position"], kept["part"]) == (stream["pages"][2]["key"], 2, 0.5), kept
    assert store.settings("comic:" + new["id"]) == {"direction": "rtl"}
    assert store.growth()[new["id"]]["pages"] == grown["pages"]
    row = store.covers()["comic:" + new["id"]]
    assert row["comic"] == new["id"] and row["wrote"][0].endswith(os.path.join("SomeAuthor", "MyComic.png"))
    #and nothing is left under the old id to be carried anywhere again
    assert store.progress(old["id"]) is None and "comic:" + old["id"] not in store.covers()
    #the cover still shows, and reset takes the picture off the shelf at its new place
    assert api.get("/api/comics/{0}/cover".format(new["id"])).status_code == 200
    api.delete("/api/covers", params={"target": "comic:" + new["id"]})
    assert not (library / "CBZs" / "SomeAuthor" / "MyComic.png").exists()


def test_a_moved_comic_asked_for_brings_the_next_scan_forward(library, make_app):
    #between a move and the next scan the reader still shows the comic where it was: its tile's cover, or the
    #comic opened, asks for an archive that is no longer there - which is the sign to look again now
    folder = single(library)
    app = make_app()
    reader = app.state.library
    old = by_title(app, "MyComic")
    source = reader.sources.cached(old["sources"][0])
    reader.sources.forget(set())
    reader.sources.known[source["path"]] = source
    move(folder, library, "Uncompressed/SomeAuthor")
    assert not reader.wanted.is_set()
    with pytest.raises(FileNotFoundError):
        reader.sources.page(source, source["pages"][0])
    assert reader.wanted.is_set(), "a cover asked of a moved archive did not ask for a scan"
    reader.wanted.clear()
    reader.stream(old, fresh=True)
    assert reader.wanted.is_set(), "a moved comic opened did not ask for a scan"


def test_the_scan_comes_early_when_asked_rather_than_a_quarter_hour_later(library, make_app):
    import threading
    import time

    from comicreader.app import keep_scanning
    folder = single(library)
    app = make_app()
    reader = app.state.library
    threading.Thread(target=keep_scanning, args=(reader, 60, 0), daemon=True).start()
    move(folder, library, "Uncompressed/SomeAuthor")
    reader.wanted.set()
    #waited for, not slept: the comic shows at its new place as soon as the brought-forward scan is done
    deadline = time.time() + 30
    while by_title(app, "MyComic")["place"] != "CBZs/SomeAuthor" and time.time() < deadline:
        time.sleep(0.05)
    assert by_title(app, "MyComic")["place"] == "CBZs/SomeAuthor"


def test_each_chapter_keeps_its_place_and_the_chapter_folder_its_cover(library, client):
    folder = chaptered(library)
    api, app = client()
    store = app.state.store
    second = by_title(app, "Part 2")
    store.save_progress(second["id"], app.state.library.stream(second)["pages"][1]["key"], 1, 3)
    uploaded = api.put("/api/covers/upload", params={"target": "folder:CBZs/MyComic"}, content=png(30, 40, 77))
    assert uploaded.status_code == 200, uploaded.text

    move(folder, library, "Uncompressed/SomeAuthor")
    app.state.library.scan()
    moved = by_title(app, "Part 2")
    assert moved["id"] != second["id"] and store.progress(moved["id"])["position"] == 1
    covers = store.covers()
    assert "folder:CBZs/SomeAuthor/MyComic" in covers and "folder:CBZs/MyComic" not in covers, list(covers)


def test_a_place_read_since_the_move_is_not_written_over(library, make_app):
    folder = single(library)
    app = make_app()
    store = app.state.store
    old = by_title(app, "MyComic")
    keys = [page["key"] for page in app.state.library.stream(old)["pages"]]
    store.save_progress(old["id"], keys[1], 1, 4)
    move(folder, library, "Uncompressed/SomeAuthor")
    app.state.library.scan()
    new_id = by_title(app, "MyComic")["id"]
    assert store.progress(new_id)["position"] == 1
    #read on at its new place: a later scan, finding the move still written down, leaves that alone
    store.save_progress(new_id, keys[3], 3, 4)
    app.state.library.scan()
    assert store.progress(new_id)["position"] == 3


def test_a_reader_given_the_folder_above_the_scrapers_still_follows(library, make_app):
    #the reader looks at the whole of a drive, the scraper at one folder of it
    root = library / "Webcomics"
    (root / "CBZs").mkdir(parents=True)
    (root / "Uncompressed").mkdir()
    folder = single(root)
    app = make_app()
    old = by_title(app, "MyComic")
    app.state.store.save_progress(old["id"], None, 2, 4)
    move(folder, root, "Uncompressed/SomeAuthor")
    app.state.library.scan()
    assert app.state.store.progress(by_title(app, "MyComic")["id"])["position"] == 2


def test_a_comic_moved_twice_between_scans_is_still_followed(library, make_app):
    folder = single(library)
    app = make_app()
    old = by_title(app, "MyComic")
    app.state.store.save_progress(old["id"], None, 3, 4)
    move(folder, library, "Uncompressed/OneAuthor")
    move(library / "Uncompressed" / "OneAuthor" / "MyComic", library, "Uncompressed/AnotherAuthor")
    app.state.library.scan()
    assert app.state.store.progress(by_title(app, "MyComic")["id"])["position"] == 3
