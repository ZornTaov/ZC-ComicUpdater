#cutting a comic by size when its filenames cannot say which page is which: the page stops and asks rather
#than walking on its own, says why in enough detail to answer, and does what the reader chooses. a page
#held twice - the same image under a name an older scrape gave a second extension - has one copy set aside,
#not deleted; a walk that never got past one page, and so stands in the way of the numbers, is discarded
#by renaming it aside. nothing here reaches a site: a walk would have nothing to walk.
import os
import zipfile

import pytest

from conftest import open_page, read_meta, wait_until, write_index, write_meta

NAME = "Uncompressed/Twice"


def held_twice(library, name="Twice", differ=False):
    #page 2 saved by two scrapes: once plainly, once with the extension added a second time
    folder = library / "Uncompressed" / name
    folder.mkdir()
    for at, file in enumerate(["0001.png", "0002.png", "0003.png", "0004.png"]):
        (folder / file).write_bytes(bytes([at]) * (300 + at))
    (folder / "0002.png.png").write_bytes(bytes([9 if differ else 1]) * 301)
    write_meta(folder, {"schema": 2, "settings": {"url": "https://example.com/comic/1/",
                                                  "output": "Uncompressed/" + name,
                                                  "cbz_path": "CBZs/{0}.cbz".format(name)}, "history": {}})
    return folder


def finished(page, job):
    #the job as Recent shows it once it is done
    assert page.wait_idle(300), "the job never finished"
    _, state = page.call("/api/state")
    return next(entry for entry in state["history"] if entry["id"] == job)


def parts(folder):
    return [(c["start_page"], c["end_page"]) for c in read_meta(folder)["chapters"]["list"]]


def test_a_page_held_twice_stops_to_ask_rather_than_walking(library, chapters, web):
    folder = held_twice(library)
    page = web()
    code, answer = page.call("/api/chapterize", {"name": NAME, "every": "2"})
    assert code == 200, answer
    done = finished(page, answer["queued"])
    decide = done.get("decide")
    assert decide and decide["comic"] == NAME and decide["every"] == 2, done
    assert decide["twice"] == [{"page": 2, "identical": True, "files": [
        {"name": "0002.png", "bytes": 301}, {"name": "0002.png.png", "bytes": 301}]}], decide
    assert "Walking" not in page.said() and "index ..." not in page.said(), page.said()[-800:]
    assert not read_meta(folder).get("chapters", {}).get("list")
    #the editor, opened afterwards, is shown the same question
    _, detail = page.call("/api/comic?name=" + NAME)
    assert detail["decide"]["twice"] == decide["twice"], detail["decide"]


def test_the_copy_not_kept_is_set_aside_and_the_comic_is_cut(library, chapters, web):
    folder = held_twice(library, differ=True)
    page = web()
    _, answer = page.call("/api/chapterize", {"name": NAME, "every": "2"})
    assert finished(page, answer["queued"])["decide"]["twice"][0]["identical"] is False
    code, answer = page.call("/api/chapterize", {"name": NAME, "every": "2", "set_aside": ["0002.png.png"]})
    assert code == 200, answer
    done = finished(page, answer["queued"])
    assert not done.get("decide") and not done.get("error"), done
    assert (folder / ".set aside" / "0002.png.png").exists() and not (folder / "0002.png.png").exists()
    assert parts(folder) == [(1, 2), (3, 4)], parts(folder)
    #the copy set aside is in no archive, and the page it was a copy of is
    shelf = library / "CBZs" / "Twice"
    held = []
    for name in sorted(os.listdir(str(shelf))):
        with zipfile.ZipFile(str(shelf / name)) as zf:
            held += zf.namelist()
    assert "0002.png" in held and not [name for name in held if "0002.png.png" in name], held
    #and the folder it went into is not counted as a page
    _, detail = page.call("/api/comic?name=" + NAME)
    assert detail["pages_in_folder"] == 4 and not detail["decide"], detail


def test_the_last_copy_of_a_page_is_never_set_aside(library, chapters, web):
    folder = held_twice(library)
    page = web()
    #both copies of page 2, and the only copy of page 1: none of them may go
    code, answer = page.call("/api/chapterize", {"name": NAME, "every": "2",
                                                 "set_aside": ["0002.png", "0002.png.png", "0001.png", "../x.png"]})
    assert code == 200, answer
    done = finished(page, answer["queued"])
    assert done.get("decide", {}).get("twice"), done
    assert sorted(os.listdir(str(folder))) == ["0001.png", "0002.png", "0002.png.png", "0003.png", "0004.png",
                                               "mirror_metadata.json"]
    assert "nothing else would be left on its page number" in page.said(), page.said()[-800:]


def stale_walk(chapters, library, folder):
    #a walk begun on the comic's newest page by a site whose first-page link leads there: one line, and an
    #alignment made from it
    cache = chapters.index_path(str(folder), str(library), None)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    write_index(cache, [{"n": 1, "url": "https://example.com/comic/4/", "src": "https://example.com/i/9.png",
                         "image": "9.png", "bytes": 300}])
    with open(cache.replace(".jsonl", ".align.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    meta = read_meta(folder)
    meta["history"]["index_cache"] = os.path.basename(cache)
    write_meta(folder, meta)
    return cache


def test_a_walk_that_never_got_past_one_page_is_offered_for_discarding(library, chapters, web):
    folder = held_twice(library, "Stale")
    (folder / "0002.png.png").unlink()
    cache = stale_walk(chapters, library, folder)
    page = web()
    _, detail = page.call("/api/comic?name=Uncompressed/Stale")
    assert detail["stale_walk"] is True, detail
    _, answer = page.call("/api/chapterize", {"name": "Uncompressed/Stale", "every": "2"})
    decide = finished(page, answer["queued"]).get("decide")
    assert decide and decide["stale_walk"]["pages"] == 1 and "twice" not in decide, decide
    #discarded, which renames rather than deletes, and then the numbers are what it is cut by
    code, answer = page.call("/api/discardwalk", {"name": "Uncompressed/Stale"})
    assert code == 200 and len(answer["moved"]) == 2, answer
    assert not os.path.exists(cache)
    assert [name for name in os.listdir(os.path.dirname(cache)) if ".replaced-" in name], "nothing kept aside"
    _, answer = page.call("/api/chapterize", {"name": "Uncompressed/Stale", "every": "2"})
    done = finished(page, answer["queued"])
    assert not done.get("decide"), done
    assert parts(folder) == [(1, 2), (3, 4)], parts(folder)


def test_a_walk_that_covers_the_comic_is_never_discarded(library, chapters, web):
    folder = held_twice(library, "Walked")
    cache = chapters.index_path(str(folder), str(library), None)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    write_index(cache, [{"n": n, "url": "https://example.com/comic/{0}/".format(n)} for n in range(1, 6)])
    meta = read_meta(folder)
    meta["history"]["index_cache"] = os.path.basename(cache)
    write_meta(folder, meta)
    page = web()
    code, answer = page.call("/api/discardwalk", {"name": "Uncompressed/Walked"})
    assert code == 409 and "kept" in answer["error"], answer
    assert os.path.exists(cache)


@pytest.mark.browser
@pytest.mark.slow
def test_the_editor_asks_and_sets_aside_the_copy_chosen(library, chapters, web, browser):
    folder = held_twice(library, differ=True)
    page = web()
    open_page(browser, page.base + "/")
    browser.execute_script("document.getElementById('e-every').value = '';"
                           "openEditor(arguments[0]).then(() => {"
                           "  document.getElementById('e-every').value = '2';"
                           "  document.getElementById('edit-chapterize').click(); });", NAME)
    #the copies differ, so neither is chosen for the reader, and going on without choosing is refused
    wait_until(lambda: browser.execute_script("return !document.getElementById('edit-decide').hidden"),
               limit=120, why="the editor never asked")
    said = browser.execute_script("return document.getElementById('edit-decide').innerText")
    assert "Page 2 is on 2 files" in said and "they differ" in said, said
    browser.execute_script("document.getElementById('decide-go').click()")
    assert "Choose which file to keep for page 2" in browser.execute_script(
        "return document.getElementById('edit-msg').innerText")
    browser.execute_script("document.querySelector('#edit-decide input[value=\"0002.png\"]').click();"
                           "document.getElementById('decide-go').click()")
    wait_until(lambda: (folder / ".set aside" / "0002.png.png").exists(), limit=120,
               why="the copy was never set aside")
    assert page.wait_idle(300)
    assert parts(folder) == [(1, 2), (3, 4)], parts(folder)
