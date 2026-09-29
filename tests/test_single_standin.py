#the one archive a comic keeps when it has no chapters, and the pages in it that no reader can show. they
#get the same stand-in the chapter archives get, so a page reads the same either way.
import argparse
import zipfile

import pytest

from conftest import PNG_240


@pytest.fixture
def comic(tmp_path, mirror):
    folder = tmp_path / "comic"
    folder.mkdir()
    for name in ("0101.png", "0102.png", "0104.png"):
        (folder / name).write_bytes(PNG_240 + name.encode())
    #the shape of a note for a page that is a video: what it is called run straight into the address, and
    #the note named for its page
    (folder / "0103.txt").write_text("My Comic's trailer"
                                     "https://example.com/video/abc123?feature=oembed\n", encoding="utf-8")
    #and a readme, which is not a page however many addresses it holds
    (folder / "README.txt").write_text("Saved by hand. See https://example.com/ for the comic itself.\n",
                                       encoding="utf-8")
    cbz = tmp_path / "comic.cbz"
    return folder, cbz, argparse.Namespace(output=str(folder), cbz_path=str(cbz))


def names_in(cbz):
    with zipfile.ZipFile(cbz) as zf:
        return zf.namelist()


def test_writing_the_archive_from_nothing_draws_a_page_for_the_video(comic, mirror):
    folder, cbz, args = comic
    built, added = mirror.cbz_update(args)
    assert built == str(cbz) and cbz.is_file(), (built, added)
    inside = sorted(names_in(cbz))
    assert "0103.png" in inside, "the page that is a video has no stand-in: {0}".format(inside)
    #named so it falls between the pages either side
    assert inside.index("0102.png") < inside.index("0103.png") < inside.index("0104.png"), inside
    assert "0103.txt" not in inside, "the note itself went into the archive: {0}".format(inside)
    assert "README.txt" in inside, "the readme is carried as it always was: {0}".format(inside)
    with zipfile.ZipFile(cbz) as zf:
        drawn = zf.read("0103.png")
    assert drawn[:8] == b"\x89PNG\r\n\x1a\n", drawn[:8]


def test_running_it_again_adds_nothing(comic, mirror):
    folder, cbz, args = comic
    mirror.cbz_update(args)
    _, added = mirror.cbz_update(args)
    assert added == 0, added
    assert names_in(cbz).count("0103.png") == 1, names_in(cbz)


def test_a_page_that_arrives_later_is_appended_stand_in_and_all(comic, mirror):
    folder, cbz, args = comic
    mirror.cbz_update(args)
    (folder / "0105.png").write_bytes(PNG_240 + b"0105")
    (folder / "0106.txt").write_text("Another one" + "https://example.com/v/def456\n", encoding="utf-8")
    _, added = mirror.cbz_update(args)
    inside = names_in(cbz)
    assert added == 2, added
    assert "0105.png" in inside, inside
    assert "0106.png" in inside and "0106.txt" not in inside, inside
    with zipfile.ZipFile(cbz) as zf:
        assert zf.testzip() is None, "the archive no longer opens"
