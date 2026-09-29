#adopt_comic taking a folder of pages someone else scraped and writing the metadata that makes it a comic
#update_comics can resume: the settings it writes, what it keeps from an earlier adoption, and update_comics
#building a scrape command from the result.
import json
import zipfile

import pytest

from conftest import read_meta, run, write_meta


def adopt(library, *args):
    return run("adopt_comic.py", *args, cwd=library)


@pytest.fixture
def pages(library):
    #fifty loose pages, numbered the way a prefixed scrape numbers them
    folder = library / "Uncompressed" / "MyComic"
    folder.mkdir()
    for n in range(1, 51):
        (folder / "{0:04d}_page.jpg".format(n)).write_bytes(b"x")
    return folder


@pytest.fixture
def from_archive(library):
    #an empty folder whose pages are all in the archive on the shelf
    folder = library / "Uncompressed" / "OtherComic"
    folder.mkdir()
    with zipfile.ZipFile(str(library / "CBZs" / "OtherComic.cbz"), "w") as zf:
        for n in range(1, 13):
            zf.writestr("{0:04d}_page.jpg".format(n), b"x")
    return folder


ADOPT_PAGES = ["Uncompressed/MyComic", "--root", ".", "--last-url", "https://example.com/50",
               "--increment", "50", "--prefix", "--cbz-path", "CBZs/MyComic.cbz"]
ADOPT_ARCHIVE = ["Uncompressed/OtherComic", "--root", ".", "--last-url", "https://example.com/12",
                 "--cbz-path", "CBZs/OtherComic.cbz", "--prefix"]


def test_an_archive_path_that_does_not_exist_is_refused(library, pages):
    #an archive that is not there is built by default now (see test_makecbz); the refusal is what a
    #library asks for with --no-make-cbz
    done = adopt(library, *ADOPT_PAGES, "--no-make-cbz")
    assert done.returncode != 0 and "does not exist" in done.stdout, done.stdout.strip()[:200]


def test_a_folder_of_pages_is_adopted_with_plain_settings(library, pages):
    with zipfile.ZipFile(str(library / "CBZs" / "MyComic.cbz"), "w") as zf:
        zf.writestr("0001_page.jpg", b"x")
    done = adopt(library, *ADOPT_PAGES)
    assert done.returncode == 0, done.stdout.strip()[-200:]
    meta = read_meta(pages)
    assert meta.get("schema") == 2
    assert meta["settings"]["prefix"] is True, "prefix is a plain value"
    assert meta["settings"]["increment"] == 50
    assert meta["settings"]["cbz_path"] == "CBZs/MyComic.cbz"
    #the command is rebuilt from the settings every run, so none of it is written down
    text = json.dumps(meta)
    assert "resume_argv" not in text and "resume_command_line" not in text


def test_an_empty_folder_paired_with_an_archive_still_adopts(library, from_archive):
    done = adopt(library, *ADOPT_ARCHIVE)
    assert done.returncode == 0, done.stdout.strip()[-200:]
    meta = read_meta(from_archive)
    assert meta["state"]["page_count"] == 12, "the page count is read out of the cbz"
    assert meta["settings"]["increment"] == 12, "the increment is inferred from the archive"


@pytest.fixture
def adopted(library, pages, from_archive):
    #both comics adopted, the way the sections after the first two found them
    with zipfile.ZipFile(str(library / "CBZs" / "MyComic.cbz"), "w") as zf:
        zf.writestr("0001_page.jpg", b"x")
    for args in (ADOPT_PAGES, ADOPT_ARCHIVE):
        done = adopt(library, *args)
        assert done.returncode == 0, done.stdout.strip()[-200:]
    return pages, from_archive


def test_force_keeps_what_only_an_earlier_run_knew(library, adopted):
    folder = adopted[0]
    meta = read_meta(folder)
    meta["state"]["image_xpath"] = "//kept/xpath"
    meta["history"]["runs"] = [{"run_id": "earlier", "argv": ["-o", "x"]}]
    write_meta(folder, meta)
    done = adopt(library, "Uncompressed/MyComic", "--root", ".", "--last-url", "https://example.com/51",
                 "--increment", "51", "--prefix", "--cbz-path", "CBZs/MyComic.cbz", "--force")
    assert done.returncode == 0, done.stdout.strip()[-200:]
    meta = read_meta(folder)
    assert meta["state"]["image_xpath"] == "//kept/xpath"
    assert len(meta["history"]["runs"]) == 1, meta["history"]["runs"]
    assert meta["settings"]["increment"] == 51


def test_update_comics_builds_commands_from_the_adopted_files(library, adopted):
    done = run("update_comics.py", ".", "--dry-run", cwd=library)
    assert done.stdout.count("--output") == 2, "both comics found:\n" + done.stdout
    assert done.stdout.count("--prefix") == 2, "prefix made it into the command:\n" + done.stdout


def test_a_comic_marked_ended_is_skipped(library, adopted):
    folder = adopted[1]
    meta = read_meta(folder)
    meta["settings"]["ended"] = True
    write_meta(folder, meta)
    done = run("update_comics.py", ".", "--dry-run", cwd=library)
    #ended comics are counted in one line rather than listed, so the one skipped for a real fault stands out
    assert "1 comic(s) left alone as ended" in done.stdout, done.stdout
    assert "Uncompressed/OtherComic" not in done.stdout, done.stdout
