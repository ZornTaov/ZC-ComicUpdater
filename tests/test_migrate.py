#metadata in the first way it was ever written, read as it is written now: the archive kept as archive_path
#becomes the setting, and anything written into the file since - chapters, which chapters.py adds to a file
#in whatever schema it finds - comes across rather than being dropped.
from comiclib.metadata import SCHEMA, migrate

OLD = {
    "generator": "adopt_comic.py",
    "output_folder": "Uncompressed/SomeAuthor/TheirComic",
    "archive_path": "CBZs/SomeAuthor/TheirComic.cbz",
    "page_count": 100,
    "ended": True,
    "adopted": True,
    "resume_argv": None,
    "chapters": {"source": "every", "every": 50, "folder": "CBZs/SomeAuthor/TheirComic",
                 "list": [{"number": 1, "label": "Pages 1-50", "start_page": 1, "end_page": 50}]},
}


def test_the_archive_kept_as_archive_path_becomes_the_setting():
    fresh = migrate(OLD)
    assert fresh["schema"] == SCHEMA
    assert fresh["settings"]["cbz_path"] == "CBZs/SomeAuthor/TheirComic.cbz"
    assert fresh["settings"]["ended"] is True


def test_chapters_written_into_an_old_file_come_across():
    #dropped, a reader would take the comic's chapter archives for a comic of their own, and migrating the
    #library would throw away chapters that took minutes to work out
    assert migrate(OLD)["chapters"] == OLD["chapters"]


def test_a_current_file_is_left_as_it_is():
    assert migrate({"schema": SCHEMA, "settings": {}}) is None
