#adopt_comic building the archive a cbz_path names when it is not there yet, rather than refusing - and
#the cases where it still refuses, or builds nothing, because building would be the wrong thing to do.
import os
import shutil
import zipfile

import pytest

from conftest import run


@pytest.fixture
def root(library):
    #laid out like a real library, with the CBZs shelf beside Uncompressed: that shelf is how a --root one
    #folder too deep is recognised
    return library


def comic(root, name, pages=3, sub=False):
    folder = root / "Uncompressed" / name
    folder.mkdir(parents=True)
    for at in range(1, pages + 1):
        (folder / "{0:04d}_page.png".format(at)).write_bytes(b"IMAGE" + str(at).encode())
    #a stray that is not a page, which must not end up in the archive
    (folder / "Thumbs.db").write_bytes(b"junk")
    if sub:
        inner = folder / "extras"
        inner.mkdir()
        (inner / "9999_bonus.png").write_bytes(b"IMAGE-bonus")
    return folder


def adopt(root, name, *more, library=None):
    done = run("adopt_comic.py", os.path.join("Uncompressed", name), "--root", library or root,
               "--last-url", "http://example.com/p3", "--force", *more, cwd=root)
    return done.returncode, done.stdout + done.stderr


def named(path):
    #what the archive holds of the comic's folder. every archive also has a ComicInfo written for it, which
    #tests/test_comicinfo.py looks at
    with zipfile.ZipFile(str(path)) as zf:
        assert "ComicInfo.xml" in zf.namelist(), zf.namelist()
        return sorted(name for name in zf.namelist() if name != "ComicInfo.xml")


def tail(out, lines=2):
    return out.strip().splitlines()[-lines:]


@pytest.fixture
def built(root):
    #an archive made by an adoption, for the tests that need a real one lying about
    comic(root, "Built")
    code, out = adopt(root, "Built", "--cbz-path", "CBZs/Built/Built.cbz")
    assert code == 0, tail(out)
    return root / "CBZs" / "Built" / "Built.cbz"


def no_writing_left(root):
    #files are written aside and moved into place, so nothing half-written may be left behind
    leftovers = [os.path.join(where, f) for where, _, files in os.walk(str(root))
                 for f in files if f.endswith(".writing")]
    assert not leftovers, leftovers


def test_a_cbz_path_on_a_shelf_not_there_yet_is_built_not_refused(root):
    comic(root, "MyComic")
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic/MyComic.cbz")
    made = root / "CBZs" / "MyComic" / "MyComic.cbz"
    assert code == 0 and "does not exist" not in out, tail(out)
    assert made.is_file()
    assert named(made) == ["0001_page.png", "0002_page.png", "0003_page.png", "mirror_metadata.json"]
    assert "archive built : CBZs/MyComic/MyComic.cbz from 3 page(s)" in out, \
        [line for line in out.splitlines() if "archive" in line]
    no_writing_left(root)


def test_a_name_one_underscore_away_from_a_real_archive_is_a_typo_and_refused(root, built):
    comic(root, "OtherComic")
    shutil.copy(str(built), str(root / "CBZs" / "OtherComic.cbz"))
    code, out = adopt(root, "OtherComic", "--cbz-path", "CBZs/OtherComic/Other_Co_mic.cbz")
    assert code != 0 and "does not exist" in out, tail(out)
    assert "did you mean" in out and "OtherComic.cbz" in out, \
        [line for line in out.splitlines() if "mean" in line]
    assert not (root / "CBZs" / "OtherComic").is_dir(), "it built nothing"
    no_writing_left(root)


def test_no_make_cbz_keeps_the_old_refusal(root):
    comic(root, "MyComic")
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic/MyComic.cbz", "--no-make-cbz")
    assert code != 0 and "does not exist" in out, tail(out)
    assert not (root / "CBZs" / "MyComic").is_dir(), "it built nothing"
    no_writing_left(root)


def test_a_dry_run_says_what_it_would_build_and_builds_nothing(root):
    comic(root, "MyComic")
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic/MyComic.cbz", "-n")
    assert "would build   : CBZs/MyComic/MyComic.cbz from 3 page(s)" in out, tail(out, 3)
    assert not (root / "CBZs" / "MyComic").is_dir(), "it built nothing"


def test_an_archive_already_there_is_left_exactly_as_it_was(root, built):
    comic(root, "MyComic")
    already = root / "CBZs" / "MyComic.cbz"
    shutil.copy(str(built), str(already))
    was = already.read_bytes()
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic.cbz")
    assert code == 0, tail(out)
    assert already.read_bytes() == was, "the archive was rewritten"
    assert "archive built" not in out, [line for line in out.splitlines() if "archive" in line]
    no_writing_left(root)


def test_pages_in_a_subfolder_are_left_out_the_way_a_scrape_would_pack_it(root):
    comic(root, "MyComic", pages=2, sub=True)
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic/MyComic.cbz")
    assert code == 0, tail(out)
    assert named(root / "CBZs" / "MyComic" / "MyComic.cbz") == \
        ["0001_page.png", "0002_page.png", "mirror_metadata.json"]
    no_writing_left(root)


def test_nothing_loose_to_pack_yet_is_said_plainly_not_built_empty(root, built):
    empty = root / "Uncompressed" / "Empty"
    empty.mkdir()
    shutil.copy(str(built), str(empty / "Empty.cbz"))
    code, out = adopt(root, "Empty", "--cbz-path", "CBZs/Empty/Empty.cbz")
    assert code == 0, tail(out)
    assert "nothing loose to build it from yet" in out, tail(out, 3)
    assert not (root / "CBZs" / "Empty" / "Empty.cbz").exists(), "an empty archive was left"
    no_writing_left(root)


def test_a_root_one_folder_too_deep_is_refused_rather_than_build_among_the_pages(root):
    #the archive would land in among the pages, and the saved output path would go wrong with it
    comic(root, "MyComic")
    code, out = adopt(root, "MyComic", "--cbz-path", "CBZs/MyComic/MyComic.cbz",
                      library=root / "Uncompressed")
    assert code != 0 and "in among the pages" in out, tail(out)
    assert "--root one folder too deep" in out, tail(out, 1)
    assert not (root / "Uncompressed" / "CBZs").is_dir(), sorted(os.listdir(str(root / "Uncompressed")))
    assert not (root / "Uncompressed" / "MyComic" / "mirror_metadata.json").exists(), "it wrote metadata"
    no_writing_left(root)
