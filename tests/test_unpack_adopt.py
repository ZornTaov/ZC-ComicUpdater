#adopt_comic --unpack-to: a comic that exists only as an archive on the library's shelf, unpacked into a folder
#of pages and adopted there with the archive kept as its own - and every refusal made before anything is
#written, so a refused one leaves no half-made folder behind.
import hashlib
import zipfile

import pytest

from conftest import read_meta, run

PAGES = 12


def adopt(library, *args):
    return run("adopt_comic.py", *args, cwd=library)


def digest(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.fixture
def shelved(library):
    #a finished comic someone else scraped, kept only as one archive in a folder of its own on the shelf
    folder = library / "CBZs" / "MyComic"
    folder.mkdir()
    archive = folder / "MyComic.cbz"
    with zipfile.ZipFile(str(archive), "w") as zf:
        for n in range(1, PAGES + 1):
            zf.writestr("{0:04d}.jpg".format(n), "page {0}".format(n))
        zf.writestr("Thumbs.db", b"not a page")
    return archive


def test_an_archive_is_unpacked_and_adopted_with_itself_as_its_archive(library, shelved):
    before = digest(shelved)
    done = adopt(library, "CBZs/MyComic/MyComic.cbz", "--unpack-to", "Uncompressed/MyComic", "--ended",
                 "--root", ".")
    assert done.returncode == 0, done.stdout[-600:]
    folder = library / "Uncompressed" / "MyComic"
    assert sorted(p.name for p in folder.iterdir() if p.suffix == ".jpg") == \
        ["{0:04d}.jpg".format(n) for n in range(1, PAGES + 1)], "every page, and nothing that is not one"
    assert (folder / "0003.jpg").read_text() == "page 3"
    settings = read_meta(folder)["settings"]
    assert settings["output"] == "Uncompressed/MyComic"
    assert settings["cbz_path"] == "CBZs/MyComic/MyComic.cbz", "the archive that was there is the comic's own"
    assert settings["ended"] is True
    assert digest(shelved) == before, "the archive itself is left exactly as it was"
    assert not [p for p in (library / "Uncompressed").iterdir() if p.name.startswith(".")], \
        "nothing left over from unpacking"


def test_without_an_address_or_ended_nothing_is_unpacked(library, shelved):
    done = adopt(library, "CBZs/MyComic/MyComic.cbz", "--unpack-to", "Uncompressed/MyComic", "--root", ".")
    assert done.returncode != 0
    assert "needs an address, or ended" in done.stdout, done.stdout[-400:]
    assert not (library / "Uncompressed" / "MyComic").exists()


def test_a_folder_that_already_holds_files_is_not_unpacked_into(library, shelved):
    folder = library / "Uncompressed" / "MyComic"
    folder.mkdir()
    (folder / "0001.jpg").write_text("someone else's page 1")
    done = adopt(library, "CBZs/MyComic/MyComic.cbz", "--unpack-to", "Uncompressed/MyComic", "--ended",
                 "--root", ".")
    assert done.returncode != 0
    assert "already holds files" in done.stdout, done.stdout[-400:]
    assert (folder / "0001.jpg").read_text() == "someone else's page 1", "and what was there is untouched"


def test_an_archive_with_pages_in_several_folders_is_refused_untouched(library):
    #a comic and its extras, or chapters as folders: no single order to read them in
    (library / "CBZs" / "Mixed").mkdir()
    with zipfile.ZipFile(str(library / "CBZs" / "Mixed" / "Mixed.cbz"), "w") as zf:
        zf.writestr("Chapter 1/0001.jpg", "a")
        zf.writestr("Chapter 2/0001.jpg", "b")
    done = adopt(library, "CBZs/Mixed/Mixed.cbz", "--unpack-to", "Uncompressed/Mixed", "--ended", "--root", ".")
    assert done.returncode != 0
    assert "different folders" in done.stdout, done.stdout[-400:]
    assert not (library / "Uncompressed" / "Mixed").exists()


def monthly(library, name, layout):
    #an archive kept the way the site kept its images: a folder a month, each page named for its date
    (library / "CBZs" / name).mkdir()
    with zipfile.ZipFile(str(library / "CBZs" / name / (name + ".cbz")), "w") as zf:
        for entry in layout:
            zf.writestr(entry, entry)
    return "CBZs/{0}/{0}.cbz".format(name)


def test_an_archive_kept_a_folder_a_month_is_flattened_flash_pages_and_all(library):
    archive = monthly(library, "Dated", ["0004/000402.png", "0004/000401.png", "0005/000501.swf",
                                         "0005/000502.gif", "readme.txt"])
    done = adopt(library, archive, "--unpack-to", "Uncompressed/Dated", "--ended", "--root", ".", "--flatten")
    assert done.returncode == 0, done.stdout[-500:]
    folder = library / "Uncompressed" / "Dated"
    assert sorted(p.name for p in folder.iterdir() if p.name != "mirror_metadata.json") == \
        ["000401.png", "000402.png", "000501.swf", "000502.gif"], \
        "every page from every month in one folder - the flash page too, which packing draws a stand-in for"


def test_flattening_refuses_a_name_in_two_folders(library):
    archive = monthly(library, "Clash", ["a/0001.png", "b/0001.png", "b/0002.png"])
    done = adopt(library, archive, "--unpack-to", "Uncompressed/Clash", "--ended", "--root", ".", "--flatten")
    assert done.returncode != 0
    assert "more than one of its folders" in done.stdout, done.stdout[-400:]
    assert not (library / "Uncompressed" / "Clash").exists()


def test_a_dry_run_says_what_it_would_do_and_does_nothing(library, shelved):
    done = adopt(library, "CBZs/MyComic/MyComic.cbz", "--unpack-to", "Uncompressed/MyComic", "--ended",
                 "--root", ".", "--dry-run")
    assert done.returncode == 0, "a dry run is not a failure\n" + done.stdout[-400:]
    assert "{0} page(s) into Uncompressed/MyComic".format(PAGES) in done.stdout, done.stdout[-400:]
    assert not (library / "Uncompressed" / "MyComic").exists()
