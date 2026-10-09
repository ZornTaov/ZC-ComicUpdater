#the ComicInfo.xml every archive carries: a picture's size read from its first bytes, the elements in the order
#the v2.1 draft schema insists on, and an archive added to keeping exactly one, written on the end where an
#append writes, so the bytes already there stay where they were.
import os
import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

from comiclib import cbz, comicinfo
from comiclib.metadata import METADATA_FILE
from conftest import run, write_meta

#the schema's sequence, which a strict reader holds an archive to
SCHEMA_ORDER = ["Title", "Series", "Number", "Count", "Volume", "AlternateSeries", "AlternateNumber",
                "AlternateCount", "Summary", "Notes", "Year", "Month", "Day", "Writer", "Penciller", "Inker",
                "Colorist", "Letterer", "CoverArtist", "Editor", "Translator", "Publisher", "Imprint", "Genre",
                "Tags", "Web", "PageCount", "LanguageISO", "Format", "BlackAndWhite", "Manga", "Characters",
                "Teams", "Locations", "ScanInformation", "StoryArc", "StoryArcNumber", "SeriesGroup",
                "AgeRating", "Pages", "CommunityRating", "MainCharacterOrTeam", "Review", "GTIN"]
PAGE_ORDER = ["Image", "Type", "DoublePage", "ImageSize", "Key", "Bookmark", "ImageWidth", "ImageHeight"]


def png(width, height):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"


def jpeg(width, height, padding=0):
    #an exif block ahead of the frame, the way a camera or an editor leaves one, as long as asked
    app1 = b"\xff\xe1" + struct.pack(">H", padding + 2) + b"\x00" * padding
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\x00" * 9
    return b"\xff\xd8" + app1 + frame + b"\xff\xd9"


@pytest.mark.parametrize("head, shape", [
    (png(800, 1200), (800, 1200)),
    (b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 6, (640, 480)),
    (b"BM" + b"\x00" * 12 + struct.pack("<Iii", 40, 1000, -1500) + b"\x00" * 8, (1000, 1500)),
    (b"BM" + b"\x00" * 12 + struct.pack("<IHH", 12, 300, 200), (300, 200)),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 10 + struct.pack("<HH", 1024, 768), (1024, 768)),
    (b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x00" * 8 + (1599).to_bytes(3, "little") + (899).to_bytes(3, "little"),
     (1600, 900)),
    (jpeg(900, 1300), (900, 1300)),
    (jpeg(900, 1300, padding=300), (900, 1300)),
])
def test_a_pictures_size_is_read_from_its_first_bytes(head, shape):
    assert comicinfo.dimensions(head) == shape


def test_a_lossless_webp_is_read_too():
    #the 14-bit width and height packed across four bytes, less one each
    width, height = 1200, 3000
    bits = (width - 1) | (height - 1) << 14
    head = b"RIFF\x00\x00\x00\x00WEBPVP8L" + b"\x00" * 4 + b"\x2f" + bits.to_bytes(4, "little")
    assert comicinfo.dimensions(head) == (width, height)


@pytest.mark.parametrize("head", [
    png(800, 1200)[:20],                      #cut off before the size
    b"\xff\xd8\xff\xe1\x00",                  #a jpeg cut off in its first marker
    b"not a picture at all",
    b"",
])
def test_what_does_not_say_its_size_is_none_rather_than_an_error(head):
    assert comicinfo.dimensions(head) is None


def test_a_jpeg_that_says_its_size_late_is_read_further():
    #a thumbnail in the exif pushes the frame past the first read
    body = jpeg(700, 1000, padding=comicinfo.HEAD + 500)
    asked = []

    def read(n):
        asked.append(n)
        return body[:n]
    assert comicinfo.measure(read) == (700, 1000)
    assert asked == [comicinfo.HEAD, comicinfo.LONG_HEAD], asked


def parsed(blob):
    return ET.fromstring(blob)


def test_elements_are_in_the_schemas_order():
    about = {"title": "Chapter 2", "series": "MyComic", "number": 2, "count": 9, "notes": "n",
             "web": "https://example.com/c2", "bookmark": "Chapter 2"}
    root = parsed(comicinfo.build(about, [comicinfo.page(10, (800, 1200), False)]))
    tags = [child.tag for child in root]
    assert tags == sorted(tags, key=SCHEMA_ORDER.index), tags
    attributes = list(root.find("Pages/Page").attrib)
    assert attributes == sorted(attributes, key=PAGE_ORDER.index), attributes


def test_each_page_says_what_a_reader_lays_it_out_by():
    pages = [comicinfo.page(100, (800, 1200), False),
             comicinfo.page(200, (2400, 1200), False),
             comicinfo.page(300, (1000, 1400), True),
             comicinfo.page(400, None, False)]
    root = parsed(comicinfo.build({"series": "MyComic", "bookmark": "Prologue"}, pages))
    first, spread, standin, unknown = root.findall("Pages/Page")
    assert first.attrib == {"Image": "0", "Type": "FrontCover", "ImageSize": "100", "Bookmark": "Prologue",
                            "ImageWidth": "800", "ImageHeight": "1200"}
    assert spread.get("DoublePage") == "true" and spread.get("Type") is None
    #a page saying where a video went is not a page of the story
    assert standin.get("Type") == "Other"
    #a page whose size could not be read says nothing about it, rather than something wrong
    assert unknown.get("ImageWidth") is None and unknown.get("DoublePage") is None
    assert root.findtext("PageCount") == "4"


def test_a_label_with_anything_in_it_still_makes_xml_a_reader_can_read():
    label = 'Part <1> & "the \x07end\''
    root = parsed(comicinfo.build({"title": label, "bookmark": label}, [comicinfo.page(1, None, False)]))
    assert root.findtext("Title") == 'Part <1> & "the end\''
    assert root.find("Pages/Page").get("Bookmark") == 'Part <1> & "the end\''


def test_a_chapter_says_how_many_there_are_only_once_the_comic_has_ended(tmp_path):
    chapter = {"number": 3, "label": "Three", "start_page": 20, "end_page": 29, "start_url": "https://example.com/20"}
    running = comicinfo.about_chapter(str(tmp_path / "MyComic"), {"settings": {"ended": False}}, chapter, 7)
    ended = comicinfo.about_chapter(str(tmp_path / "MyComic"), {"settings": {"ended": True}}, chapter, 7)
    assert running["count"] is None and ended["count"] == 7
    assert (ended["series"], ended["title"], ended["number"], ended["bookmark"]) == ("MyComic", "Three", 3, "Three")


def test_the_whole_comic_names_its_site_not_the_page_it_was_read_up_to(tmp_path):
    about = comicinfo.about_comic(str(tmp_path / "MyComic"),
                                  {"settings": {"url": "https://example.com/comic/page-512?x=1"}})
    assert about["web"] == "https://example.com/"
    assert about["series"] == "MyComic" and about.get("count") is None


def what_it_says(archive):
    with zipfile.ZipFile(str(archive)) as zf:
        names = zf.namelist()
        return names, parsed(zf.read("ComicInfo.xml"))


@pytest.fixture
def comic(tmp_path):
    folder = tmp_path / "MyComic"
    folder.mkdir()
    for n in range(1, 4):
        (folder / "{0:04d}.png".format(n)).write_bytes(png(800, 1000 + n) + b"\x00" * n)
    (folder / METADATA_FILE).write_text('{"schema": 2, "settings": {"url": "https://example.com/3"}}')
    return folder


def page_files(folder):
    return sorted(name for name in os.listdir(str(folder)) if name.endswith(".png"))


def test_a_new_archive_ends_with_its_comicinfo_then_its_metadata(comic, tmp_path):
    archive = tmp_path / "MyComic.cbz"
    cbz.write(str(archive), str(comic), page_files(comic) + [METADATA_FILE])
    names, root = what_it_says(archive)
    #both last, so a scrape adding to it takes both back and writes them after its new pages
    assert names[-2:] == ["ComicInfo.xml", METADATA_FILE], names
    assert root.findtext("PageCount") == "3" and root.findtext("Series") == "MyComic"
    assert [page.get("ImageHeight") for page in root.findall("Pages/Page")] == ["1001", "1002", "1003"]


def test_an_append_keeps_one_comicinfo_and_every_byte_already_there(comic, tmp_path):
    archive = tmp_path / "MyComic.cbz"
    cbz.write(str(archive), str(comic), page_files(comic) + [METADATA_FILE])
    with zipfile.ZipFile(str(archive)) as zf:
        pages_end = zf.getinfo("ComicInfo.xml").header_offset
    before = archive.read_bytes()

    (comic / "0004.png").write_bytes(png(2000, 1000))
    assert cbz.append(str(archive), str(comic), page_files(comic)) == 1
    names, root = what_it_says(archive)
    assert names.count("ComicInfo.xml") == 1 and names.count(METADATA_FILE) == 1, names
    #the old ComicInfo and metadata were written over, not left behind: the new page starts where they were
    assert archive.read_bytes()[:pages_end] == before[:pages_end]
    with zipfile.ZipFile(str(archive)) as zf:
        assert zf.getinfo("0004.png").header_offset == pages_end
    assert root.findtext("PageCount") == "4"
    assert root.findall("Pages/Page")[-1].get("DoublePage") == "true"


def test_an_archive_with_nothing_new_is_left_untouched(comic, tmp_path):
    archive = tmp_path / "MyComic.cbz"
    cbz.write(str(archive), str(comic), page_files(comic) + [METADATA_FILE])
    before = archive.read_bytes()
    assert cbz.append(str(archive), str(comic), page_files(comic)) == 0
    assert archive.read_bytes() == before


def test_a_page_is_measured_once_not_every_time_the_archive_grows(comic, tmp_path, monkeypatch):
    archive = tmp_path / "MyComic.cbz"
    cbz.write(str(archive), str(comic), page_files(comic) + [METADATA_FILE])
    measured = []
    real = comicinfo.measure
    monkeypatch.setattr(comicinfo, "measure", lambda read: measured.append(1) or real(read))
    (comic / "0004.png").write_bytes(png(800, 1004))
    cbz.append(str(archive), str(comic), page_files(comic))
    assert len(measured) == 1, "pages the ComicInfo already described were read again"


def test_an_archive_made_before_comicinfo_gains_one_on_the_end(comic, tmp_path):
    #the way every single archive in a library was, until now: pages and the metadata, nothing else
    archive = tmp_path / "MyComic.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        for name in page_files(comic) + [METADATA_FILE]:
            zf.write(str(comic / name), name)
    with zipfile.ZipFile(str(archive)) as zf:
        pages_end = zf.getinfo(METADATA_FILE).header_offset
    before = archive.read_bytes()
    assert cbz.retag(str(archive), str(comic), page_files(comic), comicinfo.about_comic(str(comic)))
    names, root = what_it_says(archive)
    assert archive.read_bytes()[:pages_end] == before[:pages_end]
    assert names.count("ComicInfo.xml") == 1, names
    #measured from the archive itself, since a comic's loose pages are not always still there
    assert root.find("Pages/Page").get("ImageWidth") == "800"
    assert not cbz.retag(str(archive), str(comic), page_files(comic), comicinfo.about_comic(str(comic)))


def test_a_chapter_archive_with_its_comicinfo_first_is_retold_on_the_end(comic, tmp_path):
    #how chapter archives were packed before: the ComicInfo ahead of the pages
    archive = tmp_path / "MyComic - c001 - One.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("ComicInfo.xml", "<ComicInfo><Series>MyComic</Series></ComicInfo>")
        for name in page_files(comic):
            zf.write(str(comic / name), name)
    before = archive.read_bytes()
    with zipfile.ZipFile(str(archive)) as zf:
        pages_end = max(info.header_offset + 30 + len(info.filename) + info.compress_size for info in zf.infolist())
    about = comicinfo.about_chapter(str(comic), {}, {"number": 1, "label": "One", "start_page": 1, "end_page": 3}, 1)
    assert cbz.retag(str(archive), str(comic), page_files(comic), about)
    names, root = what_it_says(archive)
    assert names.count("ComicInfo.xml") == 1 and METADATA_FILE not in names, names
    assert archive.read_bytes()[:pages_end] == before[:pages_end], "the pages moved"
    assert root.findtext("Title") == "One"


def test_a_prefixed_archive_keeps_its_prefix_with_a_comicinfo_at_the_top(comic, tmp_path):
    archive = tmp_path / "MyComic.cbz"
    cbz.write(str(archive), str(comic), page_files(comic) + [METADATA_FILE], prefix="MyComic/")
    (comic / "0004.png").write_bytes(png(800, 1004))
    cbz.append(str(archive), str(comic), page_files(comic))
    names, root = what_it_says(archive)
    assert "MyComic/0004.png" in names and "0004.png" not in names, names
    assert root.findtext("PageCount") == "4"


def test_a_stand_in_is_marked_as_not_a_page_of_the_story(comic, tmp_path):
    (comic / "0004.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    archive = tmp_path / "MyComic.cbz"
    names = page_files(comic) + ["0004.mp4", METADATA_FILE]
    cbz.write(str(archive), str(comic), names)
    _, root = what_it_says(archive)
    assert [page.get("Type") for page in root.findall("Pages/Page")] == ["FrontCover", None, None, "Other"]


def test_a_library_packed_before_comicinfo_is_given_it_on_the_end_of_each_archive(tmp_path):
    library = tmp_path / "lib"
    folder = library / "Uncompressed" / "SomeAuthor" / "TheirComic"
    folder.mkdir(parents=True)
    for n in range(1, 4):
        (folder / "{0:04d}.png".format(n)).write_bytes(png(800, 1200))
    write_meta(folder, {"schema": 2, "settings": {"url": "https://example.com/3",
                                                  "cbz_path": "CBZs/SomeAuthor/TheirComic.cbz"}})
    archive = library / "CBZs" / "SomeAuthor" / "TheirComic.cbz"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(str(archive), "w") as zf:
        for name in page_files(folder) + [METADATA_FILE]:
            zf.write(str(folder / name), name)
    before = archive.read_bytes()

    looked = run("chapters.py", "comicinfo", library, "--dry-run")
    assert "ComicInfo would be written" in looked.stdout, looked.stdout[-400:]
    assert archive.read_bytes() == before, "a dry run wrote"

    done = run("chapters.py", "comicinfo", library)
    assert done.returncode == 0 and "ComicInfo written" in done.stdout, done.stdout[-400:]
    after = archive.read_bytes()
    assert after[:before.index(b"PK\x01\x02")] == before[:before.index(b"PK\x01\x02")], "a page moved"
    names, root = what_it_says(archive)
    assert root.findtext("Series") == "TheirComic" and root.findtext("PageCount") == "3"

    #once said, nothing more to say
    again = run("chapters.py", "comicinfo", library)
    assert "ComicInfo" not in again.stdout and archive.read_bytes() == after, again.stdout[-300:]
