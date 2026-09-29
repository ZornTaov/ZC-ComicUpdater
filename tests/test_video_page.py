#a page held as a video: the site draws it, the folder keeps a recording of it. it is a page the folder
#has, so the lining up must count it - and no reader can show one, so the archives must not.
import os
import zipfile

import pytest

from conftest import PNG_240, run, write_index, write_meta


@pytest.fixture
def filmy(library, config):
    comic = library / "Uncompressed" / "Filmy"
    comic.mkdir()
    #four pages, the third of them animated and kept as a recording
    for name in ("0001.png", "0002.png", "0004.png"):
        (comic / name).write_bytes(PNG_240 + name.encode())
    (comic / "0003.mp4").write_bytes(b"not really a video, but it is named like one" * 40)
    cache = "Filmy.test.jsonl"
    write_index(config / "index" / cache,
                [{"n": n, "url": "https://x.test/p/{0}".format(n), "src": src, "file": src.rsplit("/", 1)[-1],
                  "title": "Filmy"}
                 for n, src in ((1, "https://x.test/img/0001.png"), (2, "https://x.test/img/0002.png"),
                                (3, "https://x.test/img/animated.gif"), (4, "https://x.test/img/0004.png"))])
    write_meta(comic, {"schema": 2,
                       "settings": {"url": "https://x.test/p/4", "output": str(comic), "increment": 5,
                                    "cbz_path": "CBZs/Filmy.cbz", "prefix": False, "cbz": True, "ended": False},
                       "state": {}, "history": {"index_cache": cache, "first_page_url": "https://x.test/p/1",
                                                "first_page_number": 1, "runs": []}})
    return comic


def test_lining_up_counts_the_page_held_as_video(filmy, library):
    said = run("chapters.py", "align", filmy, "--root", library).stdout
    assert "1 page(s) are held as video" in said, said[-500:]
    assert "no page claims" not in said, "the video was called a stray: " + said[-500:]
    assert "the comic has and this folder does not" not in said, "its page was called missing: " + said[-500:]
    assert "not the image the walk saw" not in said, "it was called the wrong file: " + said[-500:]
    assert "settled" in said and "NOT settled" not in said, said[-300:]


def test_the_archives_hold_a_stand_in_rather_than_the_video(filmy, library, tmp_path):
    #a comic is chaptered only once it has been lined up
    run("chapters.py", "align", filmy, "--root", library)
    starts = tmp_path / "starts.txt"
    #two of them, because one chapter over a whole comic is refused as the mistake it usually is
    starts.write_text("https://x.test/p/1 | The Start\nhttps://x.test/p/4 | After The Animation\n",
                      encoding="utf-8")
    done = run("chapters.py", "chapters", filmy, "--root", library, "--list", starts, "--save")
    assert done.returncode == 0 and "After The Animation" in done.stdout, \
        (done.returncode, done.stdout[-600:], done.stderr[-300:])
    done = run("chapters.py", "pack", filmy, "--root", library, "--replace")
    assert "stand-in" in done.stdout, done.stdout[-600:]
    built = []
    for where, _, names in os.walk(str(library / "CBZs")):
        built += [os.path.join(where, n) for n in names if n.endswith(".cbz")]
    assert len(built) == 2, built
    inside = []
    for one in built:
        with zipfile.ZipFile(one) as zf:
            inside += [n for n in zf.namelist() if not n.endswith(".json") and not n.endswith(".xml")]
    inside = sorted(inside)
    #every page is there: the three drawn ones, and the animated one as a page saying where it is, named so
    #it falls where the page belongs
    assert inside == ["0001.png", "0002.png", "0003.png", "0004.png"], inside
    assert not [n for n in inside if n.endswith(".mp4")], inside
    #the video is still in the folder, which is the copy that keeps everything
    assert (filmy / "0003.mp4").is_file(), "the video was moved or deleted"
