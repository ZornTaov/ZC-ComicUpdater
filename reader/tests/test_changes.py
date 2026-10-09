#the library changing under the reader: a comic gaining pages is seen as recently updated, and an archive or
#a folder disappearing is forgotten rather than served from its last reading - with the place kept in the
#comic waiting for it, should it come back.
import os
import shutil
import zipfile

from conftest import comic_folder, page_names, png

from comiclib import cbz


def single(library, name="MyComic", pages=4):
    folder = comic_folder(library, name, pages)
    archive = library / "CBZs" / (name + ".cbz")
    cbz.write(str(archive), str(folder), page_names(folder))
    return folder, archive


def listed(api):
    return {comic["title"]: comic for comic in api.get("/api/library").json()["comics"]}


def test_a_comic_seen_for_the_first_time_is_not_recently_updated(library, client):
    single(library)
    api, _ = client()
    assert listed(api)["MyComic"]["grew"] is None


def test_a_comic_that_gains_pages_is_recently_updated_by_how_many(library, client):
    folder, archive = single(library)
    api, _ = client()
    for n in (5, 6, 7):
        (folder / "{0:04d}_page{0}.png".format(n)).write_bytes(png(40, 60, n))
    cbz.append(str(archive), str(folder), page_names(folder))
    api.post("/api/scan")
    comic = listed(api)["MyComic"]
    assert comic["grew"] is not None and comic["added"] == 3 and comic["pages"] == 7
    #a scan that finds nothing new leaves it as it was
    api.post("/api/scan")
    assert listed(api)["MyComic"]["added"] == 3


def test_a_comic_that_loses_pages_is_not_called_updated(library, client):
    folder, archive = single(library, pages=6)
    api, _ = client()
    for name in page_names(folder)[4:]:
        os.remove(str(folder / name))
    cbz.write(str(archive), str(folder), page_names(folder))
    api.post("/api/scan")
    comic = listed(api)["MyComic"]
    assert comic["grew"] is None and comic["pages"] == 4


def test_an_archive_taken_away_leaves_no_comic_and_no_pages_behind(library, client):
    #a shelf of archives from elsewhere: one deleted between scans
    for name in ("Stays", "Goes"):
        with zipfile.ZipFile(str(library / "CBZs" / (name + ".cbz")), "w") as zf:
            zf.writestr("01.png", png(4, 4))
    api, app = client()
    gone = listed(api)["Goes"]["id"]
    os.remove(str(library / "CBZs" / "Goes.cbz"))
    #before the next scan, the comic opened answers that it has no pages rather than ones that cannot be had
    assert api.get("/api/comics/{0}".format(gone)).json()["pages"] == []
    api.post("/api/scan")
    assert sorted(listed(api)) == ["Stays"]
    assert api.get("/api/comics/{0}".format(gone)).status_code == 404
    assert not any("Goes" in path for path in app.state.library.sources.known)


def test_a_comic_whose_archive_goes_is_read_from_its_pages_and_keeps_its_place(library, client):
    folder, archive = single(library, pages=6)
    api, _ = client()
    comic_id = listed(api)["MyComic"]["id"]
    api.put("/api/comics/{0}/progress".format(comic_id), json={"position": 3})
    os.remove(str(archive))
    api.post("/api/scan")
    comic = listed(api)["MyComic"]
    assert (comic["id"], comic["kind"], comic["position"]) == (comic_id, "folder", 3)
    #and when the archive is back, it is read from again, at the same place
    cbz.write(str(archive), str(folder), page_names(folder))
    api.post("/api/scan")
    comic = listed(api)["MyComic"]
    assert (comic["kind"], comic["position"]) == ("archive", 3)


def test_chapters_taken_away_from_beside_a_comic_change_nothing_about_it(library, client):
    #chapter archives packed beside the pages by mistake, then deleted: the comic is read from its archive
    #throughout, and nothing is left of the chapters
    folder, archive = single(library, pages=4)
    beside = library / "Uncompressed" / "MyComic_chapters"
    beside.mkdir()
    names = page_names(folder)
    cbz.write(str(beside / "MyComic - c001 - One.cbz"), str(folder), names[:2])
    cbz.write(str(beside / "MyComic - c002 - Two.cbz"), str(folder), names[2:])
    api, app = client()
    assert [(c["title"], c["kind"]) for c in listed(api).values()] == [("MyComic", "archive")]
    shutil.rmtree(str(beside))
    api.post("/api/scan")
    assert [(c["title"], c["kind"], c["pages"]) for c in listed(api).values()] == [("MyComic", "archive", 4)]
    assert not any("MyComic_chapters" in path for path in app.state.library.sources.known)
