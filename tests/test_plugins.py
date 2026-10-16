#a comic another program scrapes, through a plugin: the program run in the comic's staging folder, what it
#wrote taken in as numbered pages and chapters, where it got to remembered, its ComicInfo kept, and the
#comic packed and listed like any other. the program is the example plugin's, which draws a made-up series
#and fetches nothing, so none of this reaches the internet.
import json
import os
import re
import shutil
import sys
import time
import zipfile

import pytest

from comiclib import comicinfo, exits, intake, plugins
from comiclib.pages import page_key
from conftest import PROJECT, read_meta, run, write_meta

EXAMPLE = os.path.join(PROJECT, "examples", "plugins", "example")
URL = "https://example.com/comics/MyComic"


def install(config, output=None, extra=(), hooks=True, name="example", **manifest):
    #the example plugin, put where a library keeps its plugins, changed as a test needs it
    folder = os.path.join(str(config), "plugins", name)
    shutil.copytree(EXAMPLE, folder)
    path = os.path.join(folder, "plugin.json")
    with open(path, encoding="utf-8") as f:
        said = json.load(f)
    if output:
        said["output"] = output
        said["command"] += ["--shape", {"chapter-cbz": "cbz", "chapter-folders": "folders"}.get(output, output)]
    said["command"] += list(extra)
    said["id"] = name
    said.update(manifest)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(said, f)
    if not hooks:
        os.remove(os.path.join(folder, "plugin.py"))
    return folder


def add(library, *values, folder="Uncompressed/MyComic", extra=()):
    return run("run_plugin.py", "--add", "example", folder, "url=" + URL, *values, *extra, cwd=library)


def again(library, folder="Uncompressed/MyComic", extra=()):
    return run("run_plugin.py", folder, *extra, cwd=library)


def comic(library):
    return library / "Uncompressed" / "MyComic"


def pages(library):
    return sorted(name for name in os.listdir(str(comic(library))) if name.endswith(".png"))


def set_plugin(library, **values):
    meta = read_meta(comic(library))
    meta["settings"]["plugin"].update(values)
    write_meta(comic(library), meta)


# ---------------- taking in ----------------
def test_every_chapters_001_is_a_page_of_its_own(library, config):
    install(config)
    done = add(library, "chapters=3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert pages(library) == ["0001_Chapter 1 - 001.png", "0002_Chapter 1 - 002.png",
                              "0003_Chapter 2 - 001.png", "0004_Chapter 2 - 002.png",
                              "0005_Chapter 3 - 001.png", "0006_Chapter 3 - 002.png"]
    #the reader keeps its place by this, and the archives tell one page from another by it
    assert len({page_key(name) for name in pages(library)}) == 6
    meta = read_meta(comic(library))
    assert [(c["label"], c["start_page"], c["end_page"]) for c in meta["chapters"]["list"]] == [
        ("Chapter 1", 1, 2), ("Chapter 2", 3, 4), ("Chapter 3", 5, 6)]
    assert meta["chapters"]["source"] == "plugin"
    assert meta["state"]["page_count"] == 6
    assert meta["state"]["plugin"]["last_chapter"] == "Chapter 3"
    assert not os.path.exists(os.path.join(str(comic(library)), intake.STAGING)), "staging is cleared after"


def test_the_next_run_carries_on_and_does_not_take_a_chapter_twice(library, config):
    install(config)
    add(library, "chapters=2")
    set_plugin(library, chapters=4)
    done = again(library)
    assert done.returncode == 0, done.stdout + done.stderr
    #the program was told where it got to, and fetched that chapter again, as one that goes by titles does
    assert '--after "Chapter 2"' in done.stdout
    assert "already has, not taken again: Chapter 2" in done.stdout
    assert pages(library)[-4:] == ["0005_Chapter 3 - 001.png", "0006_Chapter 3 - 002.png",
                                   "0007_Chapter 4 - 001.png", "0008_Chapter 4 - 002.png"]
    assert len(pages(library)) == 8
    meta = read_meta(comic(library))
    assert [c["label"] for c in meta["chapters"]["list"]] == ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    assert [run["pages_saved"] for run in meta["history"]["runs"]] == [4, 4]


def test_a_run_that_takes_nothing_leaves_the_metadata_as_it_was(library, config):
    install(config)
    add(library, "chapters=2")
    path = os.path.join(str(comic(library)), "mirror_metadata.json")
    before = open(path, "rb").read()
    done = again(library)
    assert done.returncode == 0
    assert open(path, "rb").read() == before


def test_folders_of_pages_are_chapters_too(library, config):
    install(config, output="chapter-folders", hooks=False)
    done = add(library, "chapters=2", "pages=3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert pages(library) == ["0001_Chapter 1 - 001.png", "0002_Chapter 1 - 002.png", "0003_Chapter 1 - 003.png",
                              "0004_Chapter 2 - 001.png", "0005_Chapter 2 - 002.png", "0006_Chapter 2 - 003.png"]
    assert [c["start_page"] for c in read_meta(comic(library))["chapters"]["list"]] == [1, 4]


def test_loose_pages_keep_their_names_and_one_archive_is_kept(library, config):
    install(config, output="pages", hooks=False)
    done = add(library, "chapters=1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert pages(library) == ["0001_001-001.png", "0002_001-002.png"]
    archive = library / "CBZs" / "MyComic.cbz"
    assert archive.exists(), "a comic in no chapters keeps one archive, on the shelf beside its pages"
    first = archive.read_bytes()
    with zipfile.ZipFile(str(archive)) as zf:
        pages_end = zf.getinfo(comicinfo.NAME).header_offset
    set_plugin(library, chapters=2)
    again(library)
    with zipfile.ZipFile(str(archive)) as zf:
        held = [name for name in zf.namelist() if name.endswith(".png")]
    assert held == ["0001_001-001.png", "0002_001-002.png", "0003_002-001.png", "0004_002-002.png"]
    #the pages already there are where they were; only what follows them is written again
    assert archive.read_bytes()[:pages_end] == first[:pages_end], "added to on the end, not rewritten"


def staged(tmp_path, held, fetched):
    #a comic holding these files, and a program that has just written these
    folder = tmp_path / "MyComic"
    (folder / intake.STAGING).mkdir(parents=True)
    for name, body in held.items():
        (folder / name).write_bytes(body)
    for name, body in fetched.items():
        (folder / intake.STAGING / name).write_bytes(body)
    return folder


def test_a_new_picture_never_writes_over_a_page_with_its_name(tmp_path):
    #a program that numbers each run's pages from 1 again, so a new page arrives called what an old one is
    folder = staged(tmp_path, {"0001_001.png": b"old page"}, {"001.png": b"a new page"})
    plugin = plugins.Plugin("p", str(tmp_path), {"output": "pages", "command": ["x"]})
    taken = intake.take_in(plugin, str(folder), {})
    assert taken.pages == ["0002_001 (2).png"]
    assert (folder / "0001_001.png").read_bytes() == b"old page"
    assert len({page_key(name) for name in os.listdir(str(folder))}) == 2


def test_the_same_page_fetched_again_is_not_taken_twice(tmp_path):
    #a program that starts from the beginning every time, keeping what it has fetched nowhere it can see
    folder = staged(tmp_path, {"0001_001.png": b"page one"}, {"001.png": b"page one", "002.png": b"page two"})
    plugin = plugins.Plugin("p", str(tmp_path), {"output": "pages", "command": ["x"]})
    taken = intake.take_in(plugin, str(folder), {})
    assert (taken.pages, taken.held) == (["0002_002.png"], 1)


def test_videos_and_flash_are_taken_in_as_pages_and_text_is_not(tmp_path):
    #a program for a site whose posts can be animations: they are pages, kept as they are in the folder, and
    #drawn as stand-ins in an archive. its own notes are not pages
    folder = staged(tmp_path, {}, {"01_a.png": b"still", "02_b.webm": b"moving", "03_c.mp4": b"also moving",
                                   "04_d.swf": b"flash", "05_e.gif": b"looping", "notes.txt": b"a log"})
    plugin = plugins.Plugin("p", str(tmp_path), {"output": "pages", "command": ["x"]})
    taken = intake.take_in(plugin, str(folder), {})
    assert taken.pages == ["0001_01_a.png", "0002_02_b.webm", "0003_03_c.mp4", "0004_04_d.swf", "0005_05_e.gif"]
    assert (folder / "0002_02_b.webm").read_bytes() == b"moving"
    assert not (folder / "notes.txt").exists()


# ---------------- the plugin saying the comic is complete ----------------
def with_ended(folder, body):
    #the example plugin with an ended() of a test's own: what a plugin for a site that says a series is
    #finished would ask it, here answered by the body given
    with open(os.path.join(folder, "plugin.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef ended(settings, state, taken):\n    " + body + "\n")
    return folder


def test_a_plugin_that_says_the_comic_is_complete_marks_it_ended(library, config):
    with_ended(install(config), "return state.get('last_chapter') == 'Chapter 2'")
    done = add(library, "chapters=2")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "says this comic is complete" in done.stdout
    meta = read_meta(comic(library))
    assert meta["settings"]["ended"] is True
    assert "plugin_ended" in meta["history"]
    assert meta["history"]["runs"][-1]["marked_ended"] is True


def test_a_run_that_takes_nothing_new_still_marks_a_comic_now_complete(library, config):
    with_ended(install(config), "return bool(settings['plugin'].get('finished'))")
    add(library, "chapters=2")
    assert not read_meta(comic(library))["settings"].get("ended")
    #the series finished since: nothing new to take in, but the plugin says so now
    set_plugin(library, finished=True)
    assert again(library).returncode == 0
    assert read_meta(comic(library))["settings"]["ended"] is True


def untick(library):
    meta = read_meta(comic(library))
    meta["settings"]["ended"] = False
    write_meta(comic(library), meta)


def test_a_comic_unticked_while_the_plugin_still_says_complete_stays_unticked(library, config):
    with_ended(install(config), "return True")
    add(library, "chapters=2")
    untick(library)
    assert again(library).returncode == 0
    assert again(library).returncode == 0
    #the person's last word stands, though the plugin says the same thing every run
    assert read_meta(comic(library))["settings"]["ended"] is False


def test_a_series_that_comes_back_and_ends_again_is_marked_again(library, config):
    with_ended(install(config), "return bool(settings['plugin'].get('finished'))")
    add(library, "chapters=2")
    set_plugin(library, finished=True)
    again(library)
    assert read_meta(comic(library))["settings"]["ended"] is True
    #the person unticks it as the series picks up again: the plugin says it is not complete, which is noted
    untick(library)
    set_plugin(library, finished=False)
    done = again(library)
    assert "will be marked ended again when it does" in done.stdout
    meta = read_meta(comic(library))
    assert meta["settings"]["ended"] is False and "plugin_ended" not in meta["history"]
    assert meta["history"]["runs"][-1]["ended_rearmed"] is True, "recorded though nothing new was taken"
    #and when it is finished once more, it is marked once more
    set_plugin(library, finished=True)
    again(library)
    assert read_meta(comic(library))["settings"]["ended"] is True


def test_no_answer_neither_marks_nor_rearms(library, config):
    #a plugin whose check fails, or that answers with something other than True or False, has not said the
    #series came back - so a comic unticked by hand is not marked again just because the check broke once
    folder = with_ended(install(config), "return settings['plugin'].get('answer')")
    add(library, "chapters=2")
    set_plugin(library, answer=True)
    again(library)
    untick(library)
    for answer in (None, "no", 0):
        set_plugin(library, answer=answer)
        again(library)
        assert "plugin_ended" in read_meta(comic(library))["history"], answer
    set_plugin(library, answer=True)
    again(library)
    assert read_meta(comic(library))["settings"]["ended"] is False


def test_a_plugin_with_no_ended_leaves_ended_alone(library, config):
    install(config)
    add(library, "chapters=2")
    meta = read_meta(comic(library))
    assert not meta["settings"].get("ended")
    assert "plugin_ended" not in meta["history"]


def test_only_a_plain_true_marks_a_comic_ended(library, config):
    #a plugin answering with something that happens to be truthy - a status string, a count - has not said yes
    with_ended(install(config), "return 'finished'")
    add(library, "chapters=2")
    assert not read_meta(comic(library))["settings"].get("ended")


def test_a_program_that_fails_is_never_taken_as_complete(library, config):
    with_ended(install(config, extra=["--fail-after", "1"]), "return True")
    done = add(library, "chapters=3")
    assert done.returncode == exits.TOOL_FAILED, done.stdout + done.stderr
    #the plugin would say so, but a run whose program failed cannot know it has it all, so it is not asked
    assert not read_meta(comic(library))["settings"].get("ended")


def test_an_ended_that_fails_is_said_and_taken_as_no(library, config):
    with_ended(install(config), "raise RuntimeError('the site said no')")
    done = add(library, "chapters=2")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ended() failed" in done.stdout and "the site said no" in done.stdout
    assert not read_meta(comic(library))["settings"].get("ended")


# ---------------- going wrong ----------------
def test_a_program_that_fails_keeps_what_it_got_and_says_so(library, config):
    install(config, extra=["--fail-after", "1"])
    done = add(library, "chapters=3")
    assert done.returncode == exits.TOOL_FAILED, done.stdout + done.stderr
    assert "ended with exit code 3" in done.stdout
    assert pages(library) == ["0001_Chapter 1 - 001.png", "0002_Chapter 1 - 002.png"]
    run_record = read_meta(comic(library))["history"]["runs"][-1]
    assert (run_record["exit_code"], run_record["pages_saved"], run_record["completed"]) == (12, 2, False)


def test_a_program_out_of_time_is_stopped_and_what_it_got_kept(library, config):
    install(config, extra=["--slow", "30"])
    began = time.time()
    done = add(library, "chapters=3", extra=["--deadline", "3"])
    assert done.returncode == exits.TOOL_OUT_OF_TIME, done.stdout + done.stderr
    assert time.time() - began < 25, "stopped at its deadline, not left to finish"
    assert pages(library) == ["0001_Chapter 1 - 001.png", "0002_Chapter 1 - 002.png"]
    assert read_meta(comic(library))["state"]["plugin"]["last_chapter"] == "Chapter 1"


def test_what_a_killed_run_left_is_taken_in_unless_it_is_half_written(library, config):
    install(config)
    add(library, "chapters=1")
    staging = os.path.join(str(comic(library)), intake.STAGING)
    os.makedirs(staging)
    with zipfile.ZipFile(os.path.join(staging, "Chapter 2.cbz"), "w") as zf:
        zf.writestr("001.png", b"\x89PNG whole")
    with open(os.path.join(staging, "Chapter 3.cbz"), "wb") as f:
        f.write(b"PK\x03\x04 cut off part way")
    done = again(library)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Chapter 3.cbz: it will not open as an archive" in done.stdout
    assert "0003_Chapter 2 - 001.png" in pages(library)
    assert not any("Chapter 3" in name for name in pages(library)), "fetched again rather than taken half"


def test_a_comic_whose_plugin_is_missing_says_where_to_put_it(library, config):
    install(config)
    add(library, "chapters=1")
    shutil.rmtree(os.path.join(str(config), "plugins", "example"))
    done = again(library)
    assert done.returncode == exits.USAGE
    assert "put its folder in" in done.stdout


# ---------------- through update_comics ----------------
def test_update_comics_runs_a_plugin_comic_and_packs_its_chapters_with_their_comicinfo(library, config):
    install(config)
    add(library, "chapters=1")
    set_plugin(library, chapters=3)
    done = run("update_comics.py", library, "--config", config, "-t", "120", "--progress", "0")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "+4 pages" in done.stdout
    #each step after the scrape is said as it starts and how long it took, not left silent until the end
    assert "chapters: writing the chapter archives ..." in done.stdout
    assert re.search(r"chapters: pack took \d+s", done.stdout), done.stdout
    shelf = library / "CBZs" / "MyComic"
    assert sorted(os.listdir(str(shelf))) == ["MyComic - c001 - Chapter 1.cbz", "MyComic - c002 - Chapter 2.cbz",
                                             "MyComic - c003 - Chapter 3.cbz"]
    with zipfile.ZipFile(str(shelf / "MyComic - c002 - Chapter 2.cbz")) as zf:
        said = zf.read(comicinfo.NAME).decode()
    #what the program said that this never works out, kept
    for tag in ("<Publisher>Example Press</Publisher>", "<LanguageISO>en</LanguageISO>",
                "<Manga>YesAndRightToLeft</Manga>", "<Number>2</Number>"):
        assert tag in said
    assert "<Notes>Drawn by the example plugin's scraper.\nMirrored by ZC-ComicUpdater" in said
    assert "<Count>" not in said, "only the reader says a series is complete"
    assert "<PageCount>2</PageCount>" in said


def test_a_comic_started_from_the_command_line_is_packed_by_the_next_update(library, config):
    #its first chapters were taken in outside any update, so an update finding nothing new still packs them
    install(config)
    add(library, "chapters=2")
    done = run("update_comics.py", library, "--config", config, "-t", "120", "--progress", "0")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "up to date" in done.stdout
    assert sorted(os.listdir(str(library / "CBZs" / "MyComic"))) == ["MyComic - c001 - Chapter 1.cbz",
                                                                   "MyComic - c002 - Chapter 2.cbz"]
    assert read_meta(comic(library))["chapters"].get("packed")


def test_a_program_is_told_where_staging_is_in_full(library, config):
    #run inside staging, a program told a relative path writes into a copy of the comic's path nested there
    folder = os.path.join(str(config), "plugins", "writer")
    os.makedirs(folder)
    with open(os.path.join(folder, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump({"output": "pages", "fields": [], "command": [
            "{python}", "-c", "import os, sys; open(os.path.join(sys.argv[1], 'page.png'), 'wb').write(b'x')",
            "{staging}"]}, f)
    done = run("run_plugin.py", "--add", "writer", "Uncompressed/MyComic", cwd=library)
    assert done.returncode == 0, done.stdout + done.stderr
    assert pages(library) == ["0001_page.png"]


def test_a_mirror_base_comic_is_run_as_it_always_was(library):
    from comiclib import batch
    from comiclib.library import Comic
    args = type("Args", (), {"script": "/app/mirror_base.py", "timeout": 1800})()
    ordinary = Comic(str(library / "Uncompressed" / "Old"), {"settings": {"url": "https://example.com/1"}}, str(library))
    ordinary.argv = ["--output", "Uncompressed/Old", "https://example.com/1"]
    assert batch.program(ordinary, args) == [sys.executable, "/app/mirror_base.py"] + ordinary.argv
    scraped = Comic(str(library / "Uncompressed" / "New"), {"settings": {"scraper": "example"}}, str(library))
    scraped.argv = ["Uncompressed/New"]
    command = batch.program(scraped, args)
    assert command[1].endswith("run_plugin.py") and command[2:] == ["Uncompressed/New", "--deadline", "1740"]


# ---------------- plugin.json ----------------
def test_a_command_leaves_out_what_is_not_given():
    plugin = plugins.Plugin("p", "/plugins/p", {"command": [], "fields": [
        {"key": "url", "type": "url"}, {"key": "start", "type": "text"},
        {"key": "reverse", "type": "flag", "option": "--reverse-order"}, {"key": "quiet", "type": "flag"}]})
    values = plugins.command_values(plugin, {"url": URL, "plugin": {"reverse": True, "quiet": False}}, {}, "/s")
    assert plugins.fill(["{python}", "{url}", ["--start", "{start}"], "{reverse}", "{quiet}",
                         ["--from", "{last_chapter}"]], values) == [sys.executable, URL, "--reverse-order"]
    values = plugins.command_values(plugin, {"url": URL, "plugin": {"start": "Chapter 5"}}, {"last_chapter": "C9"}, "/s")
    assert plugins.fill([["--start", "{start}"], ["--from", "{last_chapter}"]], values) == [
        "--start", "Chapter 5", "--from", "C9"]
    with pytest.raises(plugins.PluginError, match="names {typo}"):
        plugins.fill(["{typo}"], values)


@pytest.mark.parametrize("manifest, said", [
    ({"output": "zips"}, "has to be one of"),
    ({"command": ["x"], "fields": [{"key": "a b", "type": "text"}]}, "no usable key"),
    ({"command": ["x"], "fields": [{"key": "a", "type": "number"}]}, "has to be one of"),
    ({"fields": []}, "has no command"),
])
def test_a_plugin_json_that_cannot_work_says_what_is_wrong(config, manifest, said):
    folder = os.path.join(str(config), "plugins", "broken")
    os.makedirs(folder)
    with open(os.path.join(folder, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    with pytest.raises(plugins.PluginError, match=said):
        plugins.load("broken")
    found, problems = plugins.installed()
    assert found == [] and len(problems) == 1


def test_settings_are_checked_against_the_plugins_fields(config):
    install(config)
    plugin = plugins.load("example", with_hooks=False)
    values, problems = plugins.check_values(plugin, {"url": URL, "chapters": "4"})
    assert problems == [] and values == {"url": URL, "chapters": 4, "pages": 2}
    _, problems = plugins.check_values(plugin, {"url": "example.com", "chapters": "-1"})
    assert problems == ["Series address must be a full http(s) address",
                        "Chapters it has must be a whole number, 0 or more"]


# ---------------- ComicInfo ----------------
def test_a_comic_with_nothing_kept_writes_the_same_bytes_as_ever():
    #build() promises the same bytes from the same input, which is how an archive's ComicInfo is known to be
    #current: written differently, every archive in a library would be rewritten at once
    page = comicinfo.page(100, (10, 20), False)
    assert comicinfo.build({"title": "T", "series": "S", "number": 2, "web": "https://example.com/",
                            "notes": "N", "bookmark": "T"}, [page]) == (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        '  <Title>T</Title>\n  <Series>S</Series>\n  <Number>2</Number>\n  <Notes>N</Notes>\n'
        '  <Web>https://example.com/</Web>\n  <PageCount>1</PageCount>\n  <Format>Web Comic</Format>\n'
        '  <Pages>\n    <Page Image="0" Type="FrontCover" ImageSize="100" Bookmark="T" ImageWidth="10" '
        'ImageHeight="20" />\n  </Pages>\n</ComicInfo>\n').encode("utf-8")


def test_what_is_typed_by_hand_beats_the_program_which_beats_what_is_worked_out(tmp_path):
    folder = tmp_path / "MyComic"
    chapter = {"number": 1, "label": "Chapter 384", "start_page": 1, "end_page": 2,
               "comicinfo": {"Title": "The Real Title", "Number": "384", "Writer": "Their Writer",
                             "Notes": "theirs", "AgeRating": "Teen", "Future": "kept"}}
    meta = {"settings": {}, "info": {"writer": "Typed Writer"}}
    about = comicinfo.about_chapter(str(folder), meta, chapter, 1)
    said = comicinfo.build(about, []).decode()
    assert "<Title>The Real Title</Title>" in said and "<Number>384</Number>" in said
    assert "<Writer>Typed Writer</Writer>" in said
    assert "<Notes>theirs\nMirrored by ZC-ComicUpdater" in said
    #in the schema's order, and one the schema does not know after everything it does
    assert said.index("<AgeRating>") > said.index("<Format>") and said.index("<Future>") > said.index("<AgeRating>")


def test_a_comicinfo_is_read_for_what_it_says_and_never_for_its_pages():
    said = comicinfo.kept_tags(b'<?xml version="1.0"?><ComicInfo xmlns="urn:x"><Title> A </Title><Count>9</Count>'
                               b'<PageCount>3</PageCount><Pages><Page Image="0"/></Pages><Empty></Empty></ComicInfo>')
    assert said == {"Title": "A"}
    assert comicinfo.kept_tags(b"not xml") == {}
