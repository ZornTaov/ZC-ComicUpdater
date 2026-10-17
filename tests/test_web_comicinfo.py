#a comic's ComicInfo edited from its editor on the web page: what it says kept in its metadata, and every
#archive it already has - its one archive, or each part it was cut into - brought up to it by a job in the
#queue. saved with nothing changed, it is still written: bringing old archives up to date is half the point.
import os
import xml.etree.ElementTree as ET
import zipfile

from comiclib import cbz
from conftest import read_meta, write_meta
from test_every import ch, unwalked

CUT = "Uncompressed/Numbered"


def says(archive):
    with zipfile.ZipFile(str(archive)) as zf:
        return ET.fromstring(zf.read("ComicInfo.xml"))


def cut_comic(library):
    folder = unwalked(library, ["{0:04d}.png".format(n) for n in range(1, 11)])
    ch(folder, library, "chapters", "--every", "4", "--save")
    code, out = ch(folder, library, "pack")
    assert code == 0, out
    return folder, sorted((library / "CBZs" / "Numbered").iterdir())


def last_outcome(page):
    return page.call("/api/state")[1]["history"][0].get("outcome")


def test_a_comic_cut_into_parts_says_it_in_every_part(library, chapters, web):
    folder, parts = cut_comic(library)
    page = web()
    code, view = page.call("/api/comicinfo?name=" + CUT)
    assert code == 200, view
    #what an empty box means, worked out as the archives are; and that each part keeps its own title
    assert view["chapters"] == 3 and view["cbz"] and view["said"] == {}
    assert (view["worked"]["series"], view["worked"]["Format"]) == ("Numbered", "Web Comic")
    assert page.call("/api/comicinfo?name=Nope")[0] == 404

    code, answer = page.call("/api/comicinfo", {"name": CUT, "updated": view["updated"], "info": {
        "writer": "SomeAuthor", "Publisher": "SomePublisher", "Manga": "YesAndRightToLeft"}})
    assert code == 200 and answer["saved"] and answer.get("queued"), answer
    assert page.wait_idle(120), "the archives were never written"
    for part, title in zip(parts, ("Pages 1-4", "Pages 5-8", "Pages 9-12")):
        root = says(part)
        assert (root.findtext("Title"), root.findtext("Writer"), root.findtext("Publisher"),
                root.findtext("Manga")) == (title, "SomeAuthor", "SomePublisher", "YesAndRightToLeft"), part
    assert last_outcome(page) == "3 archive(s) brought up to date", page.said()[-800:]
    meta = read_meta(folder)
    assert meta["info"] == {"writer": "SomeAuthor", "Publisher": "SomePublisher", "Manga": "YesAndRightToLeft"}
    assert "info.Publisher" in meta["history"]["edits"][-1]["changed"]

    #a page that never showed the reading direction leaves it be; one that took it off takes it out
    code, answer = page.call("/api/comicinfo", {"name": CUT, "updated": answer["updated"],
                                                "info": {"writer": "SomeAuthor", "Manga": ""}})
    assert code == 200 and answer["saved"], answer
    assert page.wait_idle(120)
    assert says(parts[0]).find("Manga") is None and says(parts[0]).findtext("Publisher") == "SomePublisher"

    #with nothing changed it is still written, and says there was nothing to write
    code, answer = page.call("/api/comicinfo", {"name": CUT, "updated": answer["updated"],
                                                "info": {"writer": "SomeAuthor"}})
    assert code == 200 and not answer["saved"] and answer.get("queued"), answer
    assert page.wait_idle(120)
    assert last_outcome(page) == "every archive already said it"


def test_a_comic_in_one_archive_is_told_and_bad_or_stale_edits_are_refused(library, chapters, web):
    folder = unwalked(library, ["{0:04d}.png".format(n) for n in range(1, 4)], "MyComic")
    archive = library / "CBZs" / "MyComic.cbz"
    cbz.write(str(archive), str(folder), sorted(os.listdir(str(folder))))
    before = (folder / "mirror_metadata.json").read_text(encoding="utf-8")
    page = web()
    _, view = page.call("/api/comicinfo?name=Uncompressed/MyComic")
    assert view["chapters"] == 0
    code, answer = page.call("/api/comicinfo", {"name": "Uncompressed/MyComic", "info": {"year": "soon"}})
    assert code == 400 and "Year has to be a whole number" in answer["error"], answer
    code, answer = page.call("/api/comicinfo", {"name": "Uncompressed/MyComic", "updated": "2000-01-01T00:00:00Z",
                                                "info": {"title": "My Comic"}})
    assert code == 409, answer
    assert (folder / "mirror_metadata.json").read_text(encoding="utf-8") == before
    assert page.wait_idle(30)

    code, answer = page.call("/api/comicinfo", {"name": "Uncompressed/MyComic", "updated": view["updated"],
                                                "info": {"title": "My Comic", "Imprint": "SomeImprint"}})
    assert code == 200 and answer["saved"], answer
    assert page.wait_idle(120)
    root = says(archive)
    assert (root.findtext("Title"), root.findtext("Imprint")) == ("My Comic", "SomeImprint")
    assert last_outcome(page) == "1 archive(s) brought up to date"


def test_a_comic_keeping_no_archives_is_only_saved(library, chapters, web):
    folder = unwalked(library, ["0001.png"], "Loose")
    meta = read_meta(folder)
    meta["settings"]["cbz"] = False
    write_meta(folder, meta)
    page = web()
    _, view = page.call("/api/comicinfo?name=Uncompressed/Loose")
    assert view["cbz"] is False
    code, answer = page.call("/api/comicinfo", {"name": "Uncompressed/Loose", "updated": view["updated"],
                                                "info": {"writer": "SomeAuthor"}})
    assert code == 200 and answer["saved"] and "queued" not in answer, answer
    assert read_meta(folder)["info"] == {"writer": "SomeAuthor"}
