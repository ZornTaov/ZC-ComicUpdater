#what the info page changes, written where it lasts: a scraped comic's metadata and, at once, its archives'
#ComicInfo, each put on the end as a scrape's append puts one; an archive from elsewhere, its own ComicInfo,
#with everything the page does not change left as it was. and nothing written while the scraper may be at work.
import json
import os
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from conftest import comic_folder, page_names, png
from fastapi.testclient import TestClient

from comiclib import cbz
from comicreader import editing
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


def their_archive(library, name, said):
    archive = library / "CBZs" / name
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("01.png", png(4, 4))
        zf.writestr("ComicInfo.xml", "<ComicInfo>{0}</ComicInfo>".format(said))
    return archive


def test_the_rest_of_the_schema_is_shown_and_changed_where_it_is_named(library, client):
    archive = their_archive(library, "TheirComic.cbz", "<Title>Their Comic</Title><Notes>Theirs.</Notes>"
                                                       "<LanguageISO>en</LanguageISO><Manga>No</Manga>")
    settle(library)
    api, _ = client()
    comic = find(api, "TheirComic")
    info = api.get("/api/comics/{0}/info".format(comic["id"])).json()
    assert info["says"] == {"title": "Their Comic", "LanguageISO": "en", "Manga": "No"}
    assert ["Publisher", "Publisher", False] in info["form"]["extra"]
    saved = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"title": "Their Comic", "Publisher": "SomePublisher", "Manga": ""},
                          "version": info["version"]})
    assert saved.status_code == 200, saved.text
    _, root = comicinfo_of(archive)
    #the publisher goes where the schema puts it, the reading direction taken out was, and the language, not
    #named at all, is left as it was - as are the notes, which are no form's to change
    assert [child.tag for child in root] == ["Title", "Notes", "Publisher", "LanguageISO"]
    assert saved.json()["says"]["Publisher"] == "SomePublisher"


def test_what_cannot_be_written_is_said_rather_than_dropped(library, client):
    single_comic(library)
    api, _ = client()
    comic = find(api, "MyComic")
    wrong = api.put("/api/comics/{0}/info".format(comic["id"]), json={"info": {"year": "soon", "Manga": "Sideways"}})
    assert wrong.status_code == 400
    assert "Year has to be a whole number" in wrong.json()["detail"] and "YesAndRightToLeft" in wrong.json()["detail"]


def test_a_scraped_comic_says_the_rest_of_the_schema_by_hand_too(library, client):
    folder, archive = single_comic(library)
    api, _ = client()
    comic = find(api, "MyComic")
    info = api.get("/api/comics/{0}/info".format(comic["id"])).json()
    #an empty box keeps what is worked out, which the form shows greyed: the folder's name, the site, the format
    assert info["worked"]["series"] == "MyComic" and info["worked"]["Format"] == "Web Comic"
    saved = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"writer": "SomeAuthor", "Publisher": "SomePublisher", "Format": "Webtoon"},
                          "updated": info["updated"]})
    assert saved.status_code == 200, saved.text
    metadata = json.loads((folder / "mirror_metadata.json").read_text())
    assert metadata["info"] == {"writer": "SomeAuthor", "Publisher": "SomePublisher", "Format": "Webtoon"}
    _, root = comicinfo_of(archive)
    assert (root.findtext("Publisher"), root.findtext("Format")) == ("SomePublisher", "Webtoon")
    #a page from before the rest could be said sends only the nine, and the publisher stays
    again = api.put("/api/comics/{0}/info".format(comic["id"]),
                    json={"info": {"writer": "SomeoneElse"}, "updated": saved.json()["updated"]})
    assert again.status_code == 200, again.text
    assert json.loads((folder / "mirror_metadata.json").read_text())["info"]["Publisher"] == "SomePublisher"


def a_mixed_folder(library):
    #two archives from elsewhere by different writers, a comic the scraper keeps in one archive, and one it
    #keeps in chapters, all shelved together
    their_archive(library, "Shelf/TheirOne.cbz", "<Title>One</Title><Writer>Them</Writer><Genre>Comedy</Genre>")
    their_archive(library, "Shelf/TheirTwo.cbz", "<Title>Two</Title><Writer>Others</Writer><Genre>Comedy</Genre>"
                                                 "<LanguageISO>en</LanguageISO>")
    single_comic(library)
    chaptered(library, "MyChapters", [2, 4])
    settle(library)


def test_a_folder_says_what_every_comic_in_it_says_or_that_they_differ(library, client):
    a_mixed_folder(library)
    api, _ = client()
    ids = [comic["id"] for comic in api.get("/api/library").json()["comics"]]
    said = api.post("/api/comicinfo", json={"ids": ids}).json()
    #the two chapters of one comic are one comic to change
    assert (said["comics"], said["scraped"], said["archives"]) == (4, 2, 5)
    assert said["fields"]["writer"] == {"value": None, "mixed": True}
    assert said["fields"]["LanguageISO"]["mixed"] and "title" not in said["fields"]
    assert said["fields"]["Format"]["mixed"]


def test_a_folder_changes_only_what_was_changed_in_every_archive(library, client):
    a_mixed_folder(library)
    api, _ = client()
    ids = [comic["id"] for comic in api.get("/api/library").json()["comics"]]
    said = api.post("/api/comicinfo", json={"ids": ids}).json()
    saved = api.put("/api/comicinfo", json={"ids": ids, "stamps": said["stamps"],
                                            "changes": {"Publisher": "SomePublisher", "genre": ""}})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["comics"], saved.json()["told"]) == (4, 5)
    assert saved.json()["fields"]["Publisher"] == {"value": "SomePublisher", "mixed": False}
    archives = [library / "CBZs" / "Shelf" / "TheirOne.cbz", library / "CBZs" / "Shelf" / "TheirTwo.cbz",
                library / "CBZs" / "MyComic.cbz"] + [
        library / "CBZs" / "MyChapters" / "MyChapters - c{0:03d} - Part {0}.cbz".format(n) for n in (1, 2)]
    for archive in archives:
        _, root = comicinfo_of(archive)
        assert root.findtext("Publisher") == "SomePublisher" and root.find("Genre") is None, archive
    #what was not changed is each one's own still: the writers, and each chapter's title
    assert comicinfo_of(archives[0])[1].findtext("Writer") == "Them"
    assert comicinfo_of(archives[1])[1].findtext("Writer") == "Others"
    assert comicinfo_of(archives[4])[1].findtext("Title") == "Part 2"
    assert json.loads((library / "Uncompressed" / "MyChapters" / "mirror_metadata.json").read_text())["info"] == {
        "Publisher": "SomePublisher"}


def test_a_folder_is_changed_whole_or_not_at_all(library, client):
    a_mixed_folder(library)
    api, _ = client()
    ids = [comic["id"] for comic in api.get("/api/library").json()["comics"]]
    said = api.post("/api/comicinfo", json={"ids": ids}).json()
    title = api.put("/api/comicinfo", json={"ids": ids, "changes": {"title": "All the same"}})
    assert title.status_code == 400 and "Title cannot be said" in title.json()["detail"]
    #one comic the scraper wrote moments ago refuses the lot, before any other is written
    os.utime(str(library / "CBZs" / "MyComic.cbz"), None)
    busy = api.put("/api/comicinfo", json={"ids": ids, "stamps": said["stamps"], "changes": {"Publisher": "P"}})
    assert busy.status_code == 409, busy.text
    for archive in (library / "CBZs" / "Shelf").iterdir():
        assert comicinfo_of(archive)[1].find("Publisher") is None


def test_a_long_edit_is_shown_going_while_the_reader_answers_everything_else(library, make_app, monkeypatch, capsys):
    #a comic of a hundred chapters takes minutes to write, and while it did the reader answered nothing - not
    #a page, not the library - and its log said nothing either. one request loop, as the server has
    chaptered(library, "MyChapters", [2, 4])
    settle(library)
    held, release = threading.Event(), threading.Event()
    retell = editing.retell

    def slow_retell(*args, **kwargs):
        held.set()
        release.wait(10)
        return retell(*args, **kwargs)
    monkeypatch.setattr(editing, "retell", slow_retell)
    with TestClient(make_app()) as api:
        ids = [comic["id"] for comic in api.get("/api/library").json()["comics"]]
        assert api.get("/api/comicinfo/underway").json() == {"underway": None}
        answer = {}
        saving = threading.Thread(target=lambda: answer.update(saved=api.put(
            "/api/comicinfo", json={"ids": ids, "changes": {"writer": "SomeAuthor"}})))
        saving.start()
        try:
            assert held.wait(10)
            #the library is still answered, and what is being written is said, archive by archive
            assert api.get("/api/library").status_code == 200
            now = api.get("/api/comicinfo/underway").json()["underway"]
            assert (now["what"], now["done"], now["total"]) == ("MyChapters", 0, 2)
            assert now["at"] == "MyChapters - c001 - Part 1.cbz"
            #a second edit waits its turn rather than writing the same archives beside the first
            second = api.put("/api/comicinfo", json={"ids": ids, "changes": {"genre": "Comedy"}})
            assert second.status_code == 409 and "still being written (0 of 2" in second.json()["detail"]
        finally:
            release.set()
            saving.join(10)
        assert answer["saved"].status_code == 200 and answer["saved"].json()["told"] == 2
        assert api.get("/api/comicinfo/underway").json() == {"underway": None}
    log = capsys.readouterr().out
    assert "ComicInfo of MyChapters: writing writer into 2 archives" in log
    assert "ComicInfo of MyChapters written (writer): 2 of 2 archives in" in log
