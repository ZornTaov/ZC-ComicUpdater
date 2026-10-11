#what the info page changes, written where it lasts: a scraped comic's metadata and, at once, its archives'
#ComicInfo, each put on the end as a scrape's append puts one; an archive from elsewhere, its own ComicInfo,
#with everything the page does not change left as it was. and nothing written while the scraper may be at work.
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile

from conftest import comic_folder, page_names, png

from comiclib import cbz
from test_library import chaptered

HOUR_AGO = time.time() - 3600


def settle(library):
    #everything in the library as though written an hour ago, as a library at rest is
    for current, _, files in os.walk(str(library)):
        for name in files:
            os.utime(os.path.join(current, name), (HOUR_AGO, HOUR_AGO))


def comicinfo_of(archive):
    with zipfile.ZipFile(str(archive)) as zf:
        names = zf.namelist()
        return names, ET.fromstring(zf.read("ComicInfo.xml"))


def single_comic(library):
    folder = comic_folder(library, "MyComic", 3)
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), page_names(folder) + ["mirror_metadata.json"])
    settle(library)
    return folder, archive


def find(api, name):
    return next(comic for comic in api.get("/api/library").json()["comics"] if comic["name"] == name)


def test_a_scraped_comic_is_said_to_be_something_in_its_metadata_and_its_archive_at_once(library, client):
    folder, archive = single_comic(library)
    with zipfile.ZipFile(str(archive)) as zf:
        pages_end = zf.getinfo("ComicInfo.xml").header_offset
    before = archive.read_bytes()
    api, _ = client()
    comic = find(api, "MyComic")
    info = api.get("/api/comics/{0}/info".format(comic["id"])).json()
    saved = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"title": "My Comic", "writer": "SomeAuthor", "summary": ""},
                          "updated": info["updated"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["told"] == 1 and saved.json()["about"]["writer"] == "SomeAuthor"
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    assert metadata["info"] == {"title": "My Comic", "writer": "SomeAuthor"}
    names, root = comicinfo_of(archive)
    assert (root.findtext("Title"), root.findtext("Writer")) == ("My Comic", "SomeAuthor")
    assert names.count("ComicInfo.xml") == 1 and names.count("mirror_metadata.json") == 1, names
    #the pages stay where they were; only the ComicInfo and the metadata are written again on the end
    assert archive.read_bytes()[:pages_end] == before[:pages_end]
    #and the shelf calls it what it was said to be
    assert find(api, "MyComic")["title"] == "My Comic"
    #a second change straight after is the reader's own doing, not the scraper's, so it is not refused
    again = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"title": "My Comic", "writer": "SomeoneElse"}, "updated": saved.json()["updated"]})
    assert again.status_code == 200, again.text


def test_a_change_made_over_one_it_never_saw_is_refused(library, client):
    single_comic(library)
    api, _ = client()
    comic = find(api, "MyComic")
    stale = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"writer": "SomeAuthor"}, "updated": "2000-01-01T00:00:00Z"})
    assert stale.status_code == 409 and "Reload" in stale.json()["detail"]


def test_nothing_is_written_while_the_scraper_may_be_writing(library, client):
    folder, archive = single_comic(library)
    api, _ = client()
    comic = find(api, "MyComic")
    (library / ".update_comics.lock").write_text("1234")
    locked = api.put("/api/comics/{0}/info".format(comic["id"]), json={"info": {"writer": "SomeAuthor"}})
    assert locked.status_code == 409 and "being updated" in locked.json()["detail"]
    (library / ".update_comics.lock").unlink()
    #the archive written moments ago, as a scrape's append leaves it
    os.utime(str(archive), None)
    busy = api.put("/api/comics/{0}/info".format(comic["id"]), json={"info": {"writer": "SomeAuthor"}})
    assert busy.status_code == 409 and "MyComic.cbz changed" in busy.json()["detail"]
    assert "info" not in json.loads((folder / "mirror_metadata.json").read_text())


def test_every_chapter_archive_says_it_and_keeps_its_own_title(library, client):
    chaptered(library, "MyComic", [2, 4])
    settle(library)
    api, _ = client()
    part = next(comic for comic in api.get("/api/library").json()["comics"] if comic["title"] == "Part 2")
    saved = api.put("/api/comics/{0}/info".format(part["id"]), json={"info": {"title": "Ignored", "writer": "SomeAuthor"}})
    assert saved.status_code == 200 and saved.json()["told"] == 2, saved.text
    for number in (1, 2):
        _, root = comicinfo_of(library / "CBZs" / "MyComic" / "MyComic - c{0:03d} - Part {0}.cbz".format(number))
        assert (root.findtext("Title"), root.findtext("Writer")) == ("Part {0}".format(number), "SomeAuthor")


def test_an_archive_from_elsewhere_has_its_own_comicinfo_changed_and_the_rest_kept(library, client):
    archive = library / "CBZs" / "TheirComic.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("01.png", png(4, 4))
        zf.writestr("ComicInfo.xml", "<ComicInfo><Title>Their Comic</Title><Summary>Theirs.</Summary>"
                                     "<Web>https://example.com/theirs</Web><LanguageISO>en</LanguageISO>"
                                     "<Manga>No</Manga></ComicInfo>")
    settle(library)
    api, _ = client()
    comic = find(api, "TheirComic")
    info = api.get("/api/comics/{0}/info".format(comic["id"])).json()
    saved = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"title": "Their Comic", "writer": "Them", "web": "https://example.com/theirs"},
                          "version": info["version"]})
    assert saved.status_code == 200, saved.text
    names, root = comicinfo_of(archive)
    assert names.count("ComicInfo.xml") == 1
    #the summary was cleared, the writer said, and what the page never shows is still there, in order
    assert [child.tag for child in root] == ["Title", "Writer", "Web", "LanguageISO", "Manga"]
    assert root.findtext("Writer") == "Them" and root.findtext("Manga") == "No"
    assert saved.json()["about"]["writer"] == "Them"
