#the info page: what a comic's ComicInfo says it is, the addresses it came from on the web, where it is kept,
#and how its last update went - from its metadata, or from the copy packed into an archive with no folder.
import json
import zipfile

from conftest import comic_folder, page_names, png

from comiclib import cbz
from test_library import chaptered


def by_title(api, title):
    return next(comic for comic in api.get("/api/library").json()["comics"] if comic["title"] == title)


def test_a_scraped_comic_says_what_it_is_and_where_it_came_from(library, client):
    folder = comic_folder(library, "MyComic", 3)
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    metadata["history"] = {"first_page_url": "https://example.com/MyComic/1",
                           "runs": [{"updated": "2026-10-01T00:00:00Z", "pages_saved": 2, "completed": True,
                                     "stop_reason": "no next button", "exit_code": 0}]}
    metadata["info"] = {"writer": "SomeAuthor", "summary": "A comic."}
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    cbz.write(str(library / "CBZs" / "MyComic.cbz"), str(folder), page_names(folder))
    api, _ = client()
    info = api.get("/api/comics/{0}/info".format(by_title(api, "MyComic")["id"])).json()
    assert (info["about"]["writer"], info["about"]["summary"]) == ("SomeAuthor", "A comic.")
    assert info["said"] == {"writer": "SomeAuthor", "summary": "A comic."}
    assert info["scraped"] and info["files"] == ["CBZs/MyComic.cbz"] and info["folder"] == "Uncompressed/MyComic"
    #the comic's first page, then where it is up to, then the site the archive names: each address once
    assert [link["url"] for link in info["links"]] == \
        ["https://example.com/MyComic/1", "https://example.com/"]
    assert info["lastRun"]["pages_saved"] == 2 and info["pages"] == 3


def test_a_chapter_links_to_its_own_first_page(library, client):
    folder = chaptered(library, "MyComic", [2, 4])
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    for at, chapter in enumerate(metadata["chapters"]["list"], 1):
        chapter["start_url"] = "https://example.com/MyComic/chapter-{0}".format(at)
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    api, _ = client()
    info = api.get("/api/comics/{0}/info".format(by_title(api, "Part 2")["id"])).json()
    assert info["links"][0] == {"label": "This chapter's first page", "url": "https://example.com/MyComic/chapter-2"}


def test_an_archive_from_elsewhere_says_what_its_comicinfo_does(library, client):
    with zipfile.ZipFile(str(library / "CBZs" / "TheirComic.cbz"), "w") as zf:
        zf.writestr("01.png", png(4, 4))
        zf.writestr("ComicInfo.xml", "<ComicInfo><Title>Their Comic</Title><Summary>Theirs.</Summary>"
                                     "<Genre>Comedy</Genre><Tags>a, b</Tags><Web>https://example.com/theirs</Web>"
                                     "</ComicInfo>")
    api, _ = client()
    info = api.get("/api/comics/{0}/info".format(by_title(api, "Their Comic")["id"])).json()
    assert info["about"] == {"title": "Their Comic", "summary": "Theirs.", "genre": "Comedy", "tags": "a, b",
                             "web": "https://example.com/theirs"}
    assert not info["scraped"] and info["said"] == {} and info["lastRun"] is None
    assert info["links"] == [{"label": "The archive's web address", "url": "https://example.com/theirs"}]
