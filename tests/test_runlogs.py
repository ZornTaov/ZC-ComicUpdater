#each comic's output from an update, kept a file per run: the page's log has only the line saying how a comic
#went, and what a plugin's program said along the way - which chapter it was on, why it stopped - was read
#off its pipe for Running now and thrown away. a progress bar that draws itself again with \r is kept once,
#as it was last drawn.
import io
import os
import time

from comiclib import runlogs
from conftest import run
from test_plugins import add, install, set_plugin


def followed(*chunks):
    lines, shown = [], []

    class Chunks(io.RawIOBase):
        #handed out a chunk at a time, as a pipe gives what has arrived so far
        def __init__(self):
            self.left = list(chunks)

        def read1(self, size=-1):
            return self.left.pop(0) if self.left else b""

    runlogs.follow(Chunks(), lines.append, shown.append)
    return lines, shown


def test_a_progress_bar_is_kept_as_it_was_last_drawn():
    lines, shown = followed(b"Chapter 391\n", b"\r[==  ] 1/4", b"\r[=== ] 2/4", b"\r[====] 4/4", b"\n",
                            b"Took in 4 page(s).\n")
    assert lines == ["Chapter 391", "[====] 4/4", "Took in 4 page(s)."]
    #and the page is shown each state as it is drawn, not a step behind waiting for the next one
    assert "[==  ] 1/4" in shown and "[=== ] 2/4" in shown


def test_a_bar_cut_short_by_a_message_is_kept_where_it_got_to():
    lines, _ = followed(b"\r[=   ] 1/4\r[==  ] 2/4", b"\nFAILED: 003.jpg\n")
    assert lines == ["[==  ] 2/4", "FAILED: 003.jpg"]


def test_windows_line_endings_and_a_last_line_with_no_ending():
    lines, _ = followed(b"one\r", b"\ntwo\r\nthree")
    assert lines == ["one", "two", "three"]


def test_a_week_is_kept_and_a_comic_with_none_left_loses_its_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRROR_LOGS", str(tmp_path / "logs"))
    old = runlogs.RunLog("Uncompressed/Gone", ["x"])
    old.close("up to date")
    kept = runlogs.RunLog("Uncompressed/Kept", ["x"])
    kept.close("up to date")
    long_ago = time.time() - (runlogs.keep_days + 1) * 86400
    os.utime(old.path, (long_ago, long_ago))
    runlogs.prune()
    assert not os.path.exists(os.path.dirname(old.path))
    assert os.path.exists(kept.path)


def test_a_name_reaching_out_of_the_logs_folder_stays_in_it(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRROR_LOGS", str(tmp_path / "logs"))
    folder = runlogs.comic_folder("../../etc/Odd: Name?.")
    assert os.path.commonpath([folder, str(tmp_path / "logs")]) == str(tmp_path / "logs")
    assert os.path.basename(folder) == "Odd_ Name_"


def comic_logs(tmp_path, name="Uncompressed/MyComic"):
    folder = runlogs.comic_folder(name)
    found = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    return [os.path.join(folder, entry) for entry in found]


def test_an_update_keeps_what_a_plugins_program_said(library, config, tmp_path):
    install(config)
    add(library, "chapters=1")
    set_plugin(library, chapters=3)
    done = run("update_comics.py", library, "--config", config, "-t", "120", "--progress", "0")
    assert done.returncode == 0, done.stdout + done.stderr
    #the updater's own output stays a summary
    assert "fetched Chapter 2" not in done.stdout
    logs = comic_logs(tmp_path)
    assert len(logs) == 1, logs
    with open(logs[0], encoding="utf-8") as f:
        said = f.read()
    assert said.startswith("# Uncompressed/MyComic\n")
    for line in ("Running Example", "fetched Chapter 2 (2 pages)", "fetched Chapter 3 (2 pages)",
                 "--- chapters: pack:", "# ended"):
        assert line in said, said
    assert "+4 pages" in said.splitlines()[-1]


def test_the_page_opens_a_comics_logs_and_nothing_else(library, config, web):
    install(config)
    add(library, "chapters=1")
    set_plugin(library, chapters=2)
    page = web()
    page.call("/api/update", {"names": ["Uncompressed/MyComic"]})
    state = page.wait_idle()
    assert state is not None
    finished = state["history"][0]["comics"][0]
    assert finished["log"].startswith("Uncompressed/MyComic/"), finished
    status, said = page.call("/api/log?name=" + finished["log"])
    assert status == 200 and b"fetched Chapter 2" in said
    _, detail = page.call("/api/comic?name=Uncompressed/MyComic")
    assert [entry["name"] for entry in detail["logs"]] == [finished["log"]]
    for outside in ("../config/ComicScraper.json", "../../ComicScraper.json", "Uncompressed/MyComic/nothing.log"):
        status, _ = page.call("/api/log?name=" + outside)
        assert status == 404, outside
