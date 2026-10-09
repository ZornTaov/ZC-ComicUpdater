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
                                                 stream["pages"][3])
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


def test_each_comic_says_where_it_is_shelved_and_what_its_comicinfo_calls_it(library, make_app):
    #a shelf of archives from elsewhere: some loose at the top, some in a folder per site, some issues of
    #one series with a ComicInfo each, and one comic whose folder holds nothing but its own archive
    def archive(path, info=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("01.png", png(4, 4))
            if info:
                zf.writestr("ComicInfo.xml", "<ComicInfo>{0}</ComicInfo>".format(
                    "".join("<{0}>{1}</{0}>".format(tag, value) for tag, value in info.items())))
    archive(library / "Loose_One_-_by_Some_Body.cbz")
    archive(library / "A Site" / "Their_Comic_-_by_Them.cbz")
    archive(library / "Issues" / "MyComic 02.cbz", {"Series": "MyComic", "Number": "2", "Title": "Second", "Writer": "An Author"})
    archive(library / "Issues" / "MyComic 10.cbz", {"Series": "MyComic", "Number": "10", "Title": "Tenth"})
    archive(library / "Alone" / "Alone.cbz")
    api = make_app()
    progress = {}
    by_name = {summary["name"]: summary for summary in
               (api.state.library.summary(comic, progress.get(comic["id"])) for comic in api.state.library.comics.values())}
    assert (by_name["Loose One"]["place"], by_name["Loose One"]["author"]) == ("", "Some Body")
    assert (by_name["Their Comic"]["place"], by_name["Their Comic"]["author"]) == ("A Site", "Them")
    second = by_name["MyComic 02"]
    assert (second["place"], second["title"], second["series"], second["number"], second["author"]) == \
        ("Issues", "Second", "MyComic", "2", "An Author")
    assert by_name["MyComic 10"]["number"] == "10"
    assert by_name["Alone"]["place"] == "", "a folder holding only its own comic is that comic"


def test_a_comic_whose_archive_was_moved_since_its_metadata_was_written_is_still_one_comic(library, make_app):
    #metadata in the first way it was ever written - archive_path, not settings - naming where the archive
    #was before the shelf was sorted into a folder per author
    folder = library / "Uncompressed" / "TheirComic"
    folder.mkdir(parents=True)
    for n in range(1, 4):
        (folder / "{0:04d}.png".format(n)).write_bytes(png(4, 4))
    (folder / "mirror_metadata.json").write_text(json.dumps({"archive_path": "CBZs/TheirComic.cbz",
                                                             "resume_argv": ["https://example.com/3"]}))
    moved = library / "CBZs" / "SomeAuthor" / "TheirComic.cbz"
    moved.parent.mkdir(parents=True)
    with zipfile.ZipFile(str(moved), "w") as zf:
        for n in range(1, 4):
            zf.writestr("{0:04d}.png".format(n), png(4, 4))
    app = make_app()
    comic = only(app)
    assert (comic["kind"], comic["sources"], comic["folder"]) == ("archive", [str(moved)], str(folder))


def test_a_comic_whose_chapters_were_never_recorded_is_read_from_the_chapters_of_its_name(library, make_app):
    folder = comic_folder(library, "TheirComic", 4)
    shelf = library / "CBZs" / "TheirComic"
    shelf.mkdir(parents=True)
    names = page_names(folder)
    cbz.write(str(shelf / "TheirComic - c001 - One.cbz"), str(folder), names[:2])
    cbz.write(str(shelf / "TheirComic - c002 - Two.cbz"), str(folder), names[2:])
    app = make_app()
    comic = only(app)
    assert comic["kind"] == "chapters" and len(app.state.library.stream(comic)["pages"]) == 4


def test_a_chaptered_comic_claims_its_old_single_archive_wherever_it_is_shelved(library, make_app):
    folder = chaptered(library, "MyComic", [2, 4])
    moved = library / "CBZs" / "SomeAuthor" / "MyComic.cbz"
    moved.parent.mkdir(parents=True)
    cbz.write(str(moved), str(folder), page_names(folder))
    app = make_app()
    assert only(app)["kind"] == "chapters"


def test_chapters_the_metadata_never_recorded_are_not_another_comic(library, make_app):
    #read from the single archive the scraper adds to, with a set of chapters packed beside its pages
    folder = comic_folder(library, "MyComic", 4, settings={"cbz_path": "CBZs/MyComic.cbz"})
    names = page_names(folder)
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), names)
    beside = library / "Uncompressed" / "MyComic_chapters"
    beside.mkdir()
    cbz.write(str(beside / "MyComic - c001 - One.cbz"), str(folder), names[:2])
    cbz.write(str(beside / "MyComic - c002 - Two.cbz"), str(folder), names[2:])
    app = make_app()
    assert only(app)["kind"] == "archive"


def test_two_archives_of_one_name_are_not_guessed_between(library, make_app):
    folder = comic_folder(library, "TheirComic", 2, settings={"cbz_path": "CBZs/TheirComic.cbz"})
    for author in ("One", "Two"):
        path = library / "CBZs" / author / "TheirComic.cbz"
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("01.png", png(4, 4))
    app = make_app()
    kinds = sorted(comic["kind"] for comic in app.state.library.comics.values())
    assert kinds == ["archive", "archive", "folder"], "read from its own pages, the two others listed as they are"
    assert next(c for c in app.state.library.comics.values() if c["kind"] == "folder")["folder"] == str(folder)


def test_a_chaptered_comic_with_its_old_single_archive_still_shelved_is_one_comic(library, make_app):
    folder = chaptered(library, "MyComic", [2, 4])
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), page_names(folder))
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    metadata["settings"]["cbz_path"] = "CBZs/MyComic.cbz"
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    app = make_app()
    assert only(app)["kind"] == "chapters"


def test_a_stand_in_packed_before_comicinfo_is_known_by_what_the_folder_keeps(library, make_app):
    #an archive the scraper packed before ComicInfo marked stand-ins: the drawn page is a png like any other,
    #and only the note beside the pages says what it is
    folder = comic_folder(library, "MyComic", 2, extra={"0003.txt": b"Trailer https://youtu.be/abcdefghijk"})
    archive = library / "CBZs" / "MyComic.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        for name in ("0001_page1.png", "0002_page2.png"):
            zf.write(str(folder / name), name)
        zf.writestr("0003.png", png(4, 4))
    app = make_app()
    stream = app.state.library.stream(only(app))
    assert [page["standin"] for page in stream["pages"]] == [False, False, True]


def test_a_series_is_what_comicinfo_says_never_a_shared_name(library, make_app):
    #a comic's loose pages and an unrelated archive that happens to share its name are not a series
    comic_folder(library, "Same Name", 2, settings={"cbz": False})
    with zipfile.ZipFile(str(library / "CBZs" / "Same Name.cbz"), "w") as zf:
        zf.writestr("01.png", png(4, 4))
    app = make_app()
    summaries = [app.state.library.summary(comic, None) for comic in app.state.library.comics.values()]
    assert [summary["series"] for summary in summaries] == [None, None]


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
