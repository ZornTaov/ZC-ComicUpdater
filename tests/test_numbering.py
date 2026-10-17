#a chapter's own number, read from its label, for its archive's name and its ComicInfo: the shapes chapter
#lists come in - numbered from the start, titled only, numbered by the parts of each story, a comic begun part
#way, intermissions between numbered chapters - and the archives already on the shelf under their place,
#renamed to their number rather than written again, with their covers, and the renames recorded so a reader
#carries its place across.
import os
import zipfile

import pytest

from comiclib.chapters.numbering import label_number, name_part, real_numbers, same, written
from conftest import read_meta, run, write_meta


def numbers(*labels, source="archive"):
    return real_numbers({"source": source, "list": [{"number": at, "label": label}
                                                    for at, label in enumerate(labels, 1)]})


@pytest.mark.parametrize("label, said", [
    ("Chapter 391", "391"), ("Ch. 10.5", "10.5"), ("PPGD Chapter 3", "3"), ("Book #12", "12"),
    ("Book 01 - Brings Back the 80s", "1"), ("Arc 4 - The Autumn Ball", "4"), ("Issue 30", "30"),
    ("Story 2", "2"), ("12. Off to the Movies", "12"), ("Chapter 1: Introduction", "1"),
    ("The Third Game (Part 3)", None), ("Tales From Somewhere 5½, Part 1", None), ("Grab bag 1", None),
    ("group_4", None), ("Intermission: Catty Remarks", None),
])
def test_what_number_a_label_says(label, said):
    found = label_number(label)
    assert (written(found) if found is not None else None) == said


def test_a_comic_numbered_from_its_first_chapter_is_numbered_as_it_always_was():
    assert numbers("Chapter 1", "Chapter 2", "Chapter 3") == ["1", "2", "3"]


def test_a_comic_begun_part_way_is_numbered_by_its_chapters_not_its_places():
    assert numbers("Chapter 391", "Chapter 392") == ["391", "392"]


def test_an_intermission_is_half_a_step_after_the_chapter_before_it():
    assert numbers("12. Off to the Movies", "Intermission: Catty Remarks", "13. Puppy Love") == ["12", "12.5", "13"]
    assert numbers("19. A", "Intermission: B", "Intermission: C", "20. D") == ["19", "19.5", "19.6", "20"]
    assert numbers("Chapter 1", "Chapter 2", "Afterword") == ["1", "2", "2.5"]


def test_a_prologue_ahead_of_the_first_chapter_is_nought():
    assert numbers("Prologue", "Chapter 1", "Chapter 2") == ["0", "1", "2"]
    assert numbers("Cover", "Prologue", "Chapter 1") == ["0", "0.1", "1"]


def test_a_chapter_numbered_with_a_fraction_keeps_it():
    assert numbers("Chapter 10", "Chapter 10.5", "Chapter 11") == ["10", "10.5", "11"]


@pytest.mark.parametrize("labels", [
    #titles only
    ("The Beginning", "The Moon Warriors", "The Ultimate Battle"),
    #the parts of each story counted from 1 again, the way a numbered run is not
    ("The Third Game (Part 3)", "The Fourth Game (Part 1)", "The Fourth Game (Part 2)"),
    #numbers that go back
    ("Chapter 2", "Chapter 1", "Chapter 3"),
    #an intermission with no room before the next number
    ("Chapter 10", "Interlude", "Chapter 10.5"),
    #a lead-in ahead of a chapter already numbered nought
    ("Cover", "Chapter 0", "Chapter 1"),
    #more numberless chapters in a row than half steps can name
    ("Chapter 1", "a", "b", "c", "d", "e", "f", "Chapter 2"),
])
def test_a_comic_whose_labels_do_not_number_it_keeps_its_places(labels):
    assert numbers(*labels) == [str(at) for at in range(1, len(labels) + 1)]


def test_a_comic_cut_into_parts_keeps_its_places():
    assert numbers("Pages 1-100", "Pages 101-200", source="every") == ["1", "2"]


def test_a_number_goes_in_a_name_so_the_names_sort_as_the_chapters_read():
    names = [name_part(n) for n in ("0", "9", "12", "12.5", "13", "391")]
    assert names == ["000", "009", "012", "012.5", "013", "391"]
    assert sorted("c{0} - x.cbz".format(n) for n in names) == ["c{0} - x.cbz".format(n) for n in names]
    assert same("012.5", "12.5") and same("010", "10") and not same("10", "10.5")


# ---------------- packing ----------------
LABELS = ["12. Off to the Movies", "Intermission: Catty Remarks", "13. Puppy Love"]


def comic(library, labels=LABELS):
    #a comic whose files carry their page numbers, two pages a chapter, as a plugin's comic is kept
    folder = library / "Uncompressed" / "MyComic"
    folder.mkdir(parents=True)
    for page in range(1, 2 * len(labels) + 1):
        (folder / "{0:04d}_p.png".format(page)).write_bytes(b"\x89PNG" + bytes([page]) * (40 + page))
    write_meta(folder, {"schema": 2, "settings": {"output": "Uncompressed/MyComic"}, "chapters": {
        "source": "plugin", "list": [{"number": at, "label": label, "start_page": 2 * at - 1, "end_page": 2 * at,
                                      "pages": 2} for at, label in enumerate(labels, 1)]}})
    return folder


def pack(library, folder, *more):
    done = run("chapters.py", "pack", folder, "--root", library, *more)
    return done.returncode, done.stdout + done.stderr


def shelf(library):
    return sorted(os.listdir(str(library / "CBZs" / "MyComic")))


def test_an_intermissions_archive_is_named_and_told_by_its_number(library, config):
    folder = comic(library)
    code, said = pack(library, folder)
    assert code == 0, said
    assert shelf(library) == ["MyComic - c012 - 12. Off to the Movies.cbz",
                              "MyComic - c012.5 - Intermission Catty Remarks.cbz",
                              "MyComic - c013 - 13. Puppy Love.cbz"]
    with zipfile.ZipFile(str(library / "CBZs" / "MyComic" / shelf(library)[1])) as zf:
        assert "<Number>12.5</Number>" in zf.read("ComicInfo.xml").decode()


def by_place(library, folder):
    #the archives as packing named them before chapters were named by their number, with a cover beside one
    named = shelf(library)
    for at, name in enumerate(named, 1):
        old = name.replace(name.split(" - ")[1], "c{0:03d}".format(at))
        os.rename(str(library / "CBZs" / "MyComic" / name), str(library / "CBZs" / "MyComic" / old))
    cover = library / "CBZs" / "MyComic" / "MyComic - c002 - Intermission Catty Remarks.png"
    cover.write_bytes(b"\x89PNG cover")
    return {name: os.stat(str(library / "CBZs" / "MyComic" / name)).st_ino for name in shelf(library)}


def test_archives_named_by_their_place_are_renamed_not_written_again(library, config):
    folder = comic(library)
    pack(library, folder)
    before = by_place(library, folder)
    code, said = pack(library, folder)
    assert code == 0, said
    assert "renamed MyComic - c002 - Intermission Catty Remarks.cbz to MyComic - c012.5" in said
    assert shelf(library) == ["MyComic - c012 - 12. Off to the Movies.cbz",
                              "MyComic - c012.5 - Intermission Catty Remarks.cbz",
                              "MyComic - c012.5 - Intermission Catty Remarks.png",
                              "MyComic - c013 - 13. Puppy Love.cbz"]
    #the same files, renamed: nothing written again
    assert os.stat(str(library / "CBZs" / "MyComic" / shelf(library)[1])).st_ino == \
        before["MyComic - c002 - Intermission Catty Remarks.cbz"]
    assert "0 to write" in said
    #and every rename recorded, with the comic's own folder, as the reader follows moves
    moved = read_meta(folder)["history"]["moves"][-1]["moved"]
    assert moved[0] == {"what": "pages", "from": "Uncompressed/MyComic", "to": "Uncompressed/MyComic"}
    assert {"what": "chapter archive", "from": "CBZs/MyComic/MyComic - c002 - Intermission Catty Remarks.cbz",
            "to": "CBZs/MyComic/MyComic - c012.5 - Intermission Catty Remarks.cbz"} in moved
    assert {"what": "cover", "from": "CBZs/MyComic/MyComic - c002 - Intermission Catty Remarks.png",
            "to": "CBZs/MyComic/MyComic - c012.5 - Intermission Catty Remarks.png"} in moved


def test_a_dry_run_renames_nothing_and_says_what_it_would(library, config):
    folder = comic(library)
    pack(library, folder)
    before = sorted(by_place(library, folder))
    code, said = pack(library, folder, "--dry-run")
    assert code == 0, said
    assert "would rename 3 chapter archive(s)" in said
    assert "MyComic - c002 - Intermission Catty Remarks.cbz -> MyComic - c012.5 - Intermission Catty Remarks.cbz" in said
    #compared under the names they have now, so nothing reads as needing to be written again
    assert "0 to write" in said
    assert shelf(library) == before
    assert "moves" not in (read_meta(folder).get("history") or {})


def test_the_comicinfo_command_renames_by_number_too_and_packs_nothing(library, config):
    #it no longer packs a comic in chapters, but a rename writes nothing, and a library is looked over with
    #comicinfo --dry-run to see what it would rename
    folder = comic(library)
    pack(library, folder)
    before = by_place(library, folder)
    looked = run("chapters.py", "comicinfo", library, "--dry-run")
    assert "would rename 3 chapter archive(s)" in looked.stdout, looked.stdout[-500:]
    assert sorted(before) == shelf(library)
    done = run("chapters.py", "comicinfo", library)
    assert done.returncode == 0, done.stdout[-500:]
    assert "renamed MyComic - c002 - Intermission Catty Remarks.cbz to MyComic - c012.5" in done.stdout
    assert "MyComic - c012.5 - Intermission Catty Remarks.cbz" in shelf(library)
    assert "to write" not in done.stdout, done.stdout[-500:]
    assert "chapter(s) have no archive yet" not in done.stdout, done.stdout[-500:]


def test_a_new_name_already_taken_leaves_both_alone(library, config):
    folder = comic(library)
    pack(library, folder)
    keep = library / "CBZs" / "MyComic" / "MyComic - c012 - 12. Off to the Movies.cbz"
    old = library / "CBZs" / "MyComic" / "MyComic - c001 - 12. Off to the Movies.cbz"
    old.write_bytes(keep.read_bytes())
    code, said = pack(library, folder)
    assert "is already there, so neither was touched" in said
    assert old.exists() and keep.exists()
