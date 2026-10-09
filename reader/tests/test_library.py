#a comic as one stream of pages, however the scraper keeps it, and a place in it that stays put while the
#comic grows, is renumbered, or is cut into chapters.
import json
import os
import zipfile

from conftest import comic_folder, page_names, png

from comiclib import cbz, comicinfo


def chaptered(library, name, cuts, ended=False):
    #a comic packed one archive per chapter, as chapters.py pack leaves it
    total = cuts[-1]
    folder = comic_folder(library, name, total, settings={"ended": ended})
    names = page_names(folder)
    shelf = library / "CBZs" / name
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    metadata["chapters"] = {"folder": "CBZs/" + name, "list": []}
    start = 1
    for number, end in enumerate(cuts, 1):
        chapter = {"number": number, "label": "Part {0}".format(number), "start_page": start, "end_page": end}
        metadata["chapters"]["list"].append(chapter)
        cbz.write(str(shelf / "{0} - c{1:03d} - Part {1}.cbz".format(name, number)), str(folder), names[start - 1:end],
                  about=comicinfo.about_chapter(str(folder), metadata, chapter, len(cuts)))
        start = end + 1
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    return folder


def only(app):
    comics = list(app.state.library.comics.values())
    assert len(comics) == 1, [comic["title"] for comic in comics]
    return comics[0]


def test_a_single_archive_is_one_comic(library, make_app):
    folder = comic_folder(library, "MyComic", 5, settings={"ended": True})
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), page_names(folder) + ["mirror_metadata.json"])
    app = make_app()
    comic = only(app)
    stream = app.state.library.stream(comic)
    assert (comic["kind"], comic["title"], len(stream["pages"]), stream["ended"]) == ("archive", "MyComic", 5, True)


def test_chapter_archives_read_one_after_another_as_one_comic(library, make_app):
    #ten chapters, so c010 has to come after c009 and not after c001
    chaptered(library, "MyComic", [2, 4, 6, 8, 10, 12, 14, 16, 18, 20])
    app = make_app()
    comic = only(app)
    stream = app.state.library.stream(comic)
    assert comic["kind"] == "chapters" and len(stream["pages"]) == 20
    assert [page["entry"] for page in stream["pages"]][17:] == ["0018_page18.png", "0019_page19.png", "0020_page20.png"]
    assert [(chapter["title"], chapter["start"]) for chapter in stream["chapters"]][-2:] == [("Part 9", 16), ("Part 10", 18)]


def test_a_comic_kept_only_as_loose_pages_is_read_from_its_folder(library, make_app):
    comic_folder(library, "MyComic", 3, settings={"cbz": False}, extra={"0004_clip.mp4": b"video"})
    app = make_app()
    comic = only(app)
    stream = app.state.library.stream(comic)
    assert comic["kind"] == "folder"
    assert [page["standin"] for page in stream["pages"]] == [False, False, False, True]
    body, media = app.state.library.sources.page(app.state.library.sources.cached(comic["sources"][0]),
                                                 stream["pages"][3]["entry"])
    assert media == "image/png" and body.startswith(b"\x89PNG"), "the stand-in, drawn as the archive would hold it"


def test_archives_no_comic_folder_claims_are_comics_too(library, make_app):
    shelf = library / "CBZs" / "SomeAuthor"
    shelf.mkdir()
    for name in ("Their Comic - c001 - Start.cbz", "Their Comic - c002.cbz", "Standalone.cbz"):
        with zipfile.ZipFile(str(shelf / name), "w") as zf:
            zf.writestr("01.png", png(4, 4))
            zf.writestr("02.png", png(4, 4))
    app = make_app()
    by_title = {comic["title"]: comic for comic in app.state.library.comics.values()}
    assert sorted(by_title) == ["Standalone", "Their Comic"]
    stream = app.state.library.stream(by_title["Their Comic"])
    assert len(stream["pages"]) == 4
    #a chapter with no ComicInfo is named by its file, or numbered when the file names nothing
    assert [chapter["title"] for chapter in stream["chapters"]] == ["Start", "Chapter 2"]


def test_a_comic_that_grows_shows_its_new_pages_when_opened(library, make_app):
    folder = comic_folder(library, "MyComic", 3)
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder))
    app = make_app()
    comic = only(app)
    (folder / "0004_page4.png").write_bytes(png(40, 60, 4))
    cbz.append(str(archive), str(folder), page_names(folder))
    assert len(app.state.library.stream(comic)["pages"]) == 3, "the library list waits for the next scan"
    assert len(app.state.library.stream(comic, fresh=True)["pages"]) == 4, "an opened comic does not"


def test_an_archive_caught_mid_append_is_read_as_it_was(library, make_app):
    folder = comic_folder(library, "MyComic", 3)
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder))
    app = make_app()
    comic = only(app)
    #the moment the new pages are written over the old directory and the new one is not there yet
    body = archive.read_bytes()
    archive.write_bytes(body[:body.index(b"PK\x01\x02")] + b"half of a new page")
    stream = app.state.library.stream(comic, fresh=True)
    assert len(stream["pages"]) == 3, "the last good reading was kept"


def remembered_at(app, comic, position):
    stream = app.state.library.stream(comic, fresh=True)
    key = stream["pages"][position]["key"]
    return {"key": key, "position": position, "seen": len(stream["pages"])}


def test_the_place_follows_its_page_when_a_page_is_put_in_before_it(library, make_app):
    folder = comic_folder(library, "MyComic", 6)
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder))
    app = make_app()
    comic = only(app)
    progress = remembered_at(app, comic, 4)
    #a page the site's links skipped, put in as page 3: everything after is renumbered one on
    for n in range(6, 2, -1):
        os.rename(str(folder / "{0:04d}_page{0}.png".format(n)), str(folder / "{0:04d}_page{1}.png".format(n + 1, n)))
    (folder / "0003_inserted.png").write_bytes(png(40, 60, 99))
    cbz.write(str(archive), str(folder), page_names(folder))
    stream = app.state.library.stream(comic, fresh=True)
    at = app.state.library.position(stream, progress)
    assert at == 5 and stream["pages"][at]["entry"] == "0006_page5.png"


def test_the_place_follows_its_page_into_the_chapter_it_was_cut_into(library, make_app):
    folder = comic_folder(library, "MyComic", 8)
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), page_names(folder))
    app = make_app()
    progress = remembered_at(app, only(app), 6)
    #the comic is cut into chapters and its single archive given up
    os.remove(str(library / "CBZs" / "MyComic.cbz"))
    (folder / "mirror_metadata.json").unlink()
    for name in os.listdir(str(folder)):
        os.remove(str(folder / name))
    folder.rmdir()
    chaptered(library, "MyComic", [3, 8])
    app.state.library.scan()
    comic = only(app)
    stream = app.state.library.stream(comic)
    at = app.state.library.position(stream, progress)
    assert stream["pages"][at]["entry"] == "0007_page7.png" and stream["pages"][at]["source"] == 1


def test_a_page_gone_altogether_keeps_the_place_by_number(make_app, library):
    folder = comic_folder(library, "MyComic", 5)
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), page_names(folder))
    app = make_app()
    stream = app.state.library.stream(only(app))
    assert app.state.library.position(stream, {"key": "not-a-page.png", "position": 3, "seen": 5}) == 3
    assert app.state.library.position(stream, {"key": None, "position": 99, "seen": 5}) == 4
