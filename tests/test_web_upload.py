#a comic brought in through the web page as one .zip or .cbz: received, looked inside, and put in the library
#by a job - kept as it came when it was adopted already, adopted on the spot when it was not, and never over
#the top of a comic already there unless asked, and then with the old one set aside rather than lost.
import io
import json
import os
import urllib.error
import urllib.request
import zipfile

import pytest

from conftest import PNG, console_errors, open_page, read_meta, wait_until

SITE = "https://example.com"


def archive(entries):
    #a zip in memory: {name inside it: bytes}
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w", zipfile.ZIP_STORED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return held.getvalue()


def pages(count, folder="", start=1, prefixed=False):
    named = "{0:04d}_strip{0}.png" if prefixed else "{0:04d}.png"
    return {(folder + "/" if folder else "") + named.format(n): PNG + bytes([n]) for n in range(start, start + count)}


def upload(page, body, filename, kind="application/zip"):
    request = urllib.request.Request(page.base + "/api/upload", data=body, method="POST")
    request.add_header("Content-Type", kind)
    request.add_header("X-Filename", filename)
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def adopted_metadata(output="Uncompressed/Elsewhere/Old"):
    return json.dumps({"schema": 2, "settings": {"url": SITE + "/comic/12", "output": output, "increment": 12,
                                                 "prefix": True, "cbz": True},
                       "history": {"runs": [], "index_cache": "Old.1234abcd.jsonl"}}).encode()


@pytest.fixture
def page(web):
    return web()


def comic_names(page):
    return sorted(row["name"] for row in page.call("/api/comics")[1])


def test_an_adopted_comic_goes_in_as_it_came(page, library):
    entries = pages(12, "Old", prefixed=True)
    entries["Old/mirror_metadata.json"] = adopted_metadata()
    entries["Old/notes.txt"] = b"a stray file"
    code, found = upload(page, archive(entries), "Old.zip")
    assert code == 200, found
    assert found["adopted"] and found["pages"] == 12 and found["suggested"] == "Old"
    assert found["left_out"] == 1 and found["settings"]["increment"] == 12
    #a record of which page is which never comes with an upload, and that is said
    assert found["settings"]["index_cache"] == "Old.1234abcd.jsonl"
    assert [one["id"] for one in page.call("/api/uploads")[1]["uploads"]] == [found["id"]]

    code, queued = page.call("/api/upload/place", {"id": found["id"], "folder": "Brought"})
    assert code == 200, queued
    state = page.wait_idle()
    done = state["history"][0]
    assert done["kind"] == "upload" and not done.get("error"), done
    assert "kept the settings it came with" in done["outcome"]
    folder = library / "Uncompressed" / "Brought"
    assert len([n for n in os.listdir(str(folder)) if n.endswith(".png")]) == 12
    assert not (folder / "notes.txt").exists()
    #its settings follow it to where it lives now
    assert read_meta(folder)["settings"]["output"] == "Uncompressed/Brought"
    assert [name for name in comic_names(page) if name.endswith("Brought")]
    #and the upload itself is gone, and cannot be queued a second time
    assert page.call("/api/uploads")[1]["uploads"] == []
    assert page.call("/api/upload/place", {"id": found["id"], "folder": "Brought"})[0] == 404
    assert not [n for n in os.listdir(str(library / ".uploads")) if not n.startswith(".")]


def test_a_cbz_nobody_adopted_is_adopted_from_the_form(page, library):
    code, found = upload(page, archive(pages(30)), "Fresh Comic.cbz", "application/x-cbz")
    assert code == 200, found
    assert not found["adopted"] and found["numbering"] == "numbered" and found["last_number"] == 30
    assert found["suggested"] == "Fresh Comic" and found["kind"] == "cbz"
    #the form has to say where the comic is up to
    code, answer = page.call("/api/upload/place", {"id": found["id"], "folder": "Fresh Comic"})
    assert code == 400 and "where the comic is up to" in answer["error"]
    code, queued = page.call("/api/upload/place", {"id": found["id"], "folder": "Fresh Comic", "as": "pages",
                                                   "last_url": SITE + "/comic/30", "prefix": True, "increment": "30",
                                                   "every": "10"})
    assert code == 200, queued
    done = page.wait_idle()["history"][0]
    assert not done.get("error"), done
    folder = library / "Uncompressed" / "Fresh Comic"
    meta = read_meta(folder)
    assert meta["settings"]["url"] == SITE + "/comic/30"
    assert meta["settings"]["prefix"] is True and meta["settings"]["increment"] == 30
    assert meta["chapters"]["every"] == 10
    assert len([n for n in os.listdir(str(folder)) if n.endswith(".png")]) == 30


def test_a_finished_comic_can_stay_one_archive(page, library):
    code, found = upload(page, archive(pages(8)), "Done.cbz", "application/x-cbz")
    code, queued = page.call("/api/upload/place", {"id": found["id"], "folder": "Done", "as": "archive",
                                                   "ended": True})
    assert code == 200, queued
    done = page.wait_idle()["history"][0]
    assert not done.get("error"), done
    shelf = library / "CBZs" / "Done" / "Done.cbz"
    assert shelf.exists()
    with zipfile.ZipFile(str(shelf)) as zf:
        assert len(zf.namelist()) == 8
    folder = library / "Uncompressed" / "Done"
    meta = read_meta(folder)
    assert meta["settings"]["ended"] is True and meta["settings"]["cbz_path"] == "CBZs/Done/Done.cbz"
    assert not [n for n in os.listdir(str(folder)) if n.endswith(".png")]


def test_a_comic_already_there_is_set_aside_only_when_asked(page, library):
    old = library / "Uncompressed" / "Taken"
    old.mkdir(parents=True)
    (old / "0001.png").write_bytes(PNG)
    (old / "mirror_metadata.json").write_text(json.dumps({"schema": 2, "settings": {
        "url": SITE + "/comic/1", "output": "Uncompressed/Taken"}}))
    entries = pages(5, "Taken", prefixed=True)
    entries["Taken/mirror_metadata.json"] = adopted_metadata("Uncompressed/Taken")
    code, found = upload(page, archive(entries), "Taken.zip")
    code, answer = page.call("/api/upload/place", {"id": found["id"], "folder": "Taken"})
    assert code == 409 and answer["exists"] == ["Uncompressed/Taken"], answer
    code, queued = page.call("/api/upload/place", {"id": found["id"], "folder": "Taken", "replace": True})
    assert code == 200, queued
    done = page.wait_idle()["history"][0]
    assert "set the folder that was there aside" in done["outcome"], done
    assert len([n for n in os.listdir(str(old)) if n.endswith(".png")]) == 5
    aside = library / "Uncompressed" / ".replaced"
    kept = os.listdir(str(aside))
    assert len(kept) == 1 and kept[0].startswith("Taken ")
    assert (aside / kept[0] / "0001.png").exists()
    #set aside where the library scan never looks, so it is not updated as a second copy of the comic
    assert len([name for name in comic_names(page) if "Taken" in name]) == 1, comic_names(page)


@pytest.mark.parametrize("entries, why", [
    ({"../escape.png": PNG}, "outside its own folder"),
    (dict(pages(2, "A"), **pages(2, "B", start=3)), "2 different folders"),
    ({"readme.txt": b"no pages"}, "no pages"),
])
def test_what_cannot_go_in_is_refused_and_not_kept(page, library, entries, why):
    code, answer = upload(page, archive(entries), "Bad.zip")
    assert code == 400 and why in answer["error"], answer
    assert page.call("/api/uploads")[1]["uploads"] == []


@pytest.mark.browser
def test_a_comic_is_uploaded_and_adopted_from_the_page(page, library, browser, tmp_path):
    held = tmp_path / "From Elsewhere.cbz"
    held.write_bytes(archive(pages(6)))
    open_page(browser, page.base)
    browser.find_element("id", "up-file").send_keys(str(held))
    browser.find_element("id", "up-send").click()
    card = wait_until(lambda: browser.find_elements("css selector", "[data-up]"), why="no card for the upload")[0]
    assert "From Elsewhere.cbz" in card.text and "6 pages" in card.text
    assert card.find_element("css selector", '[data-f="folder"]').get_attribute("value") == "From Elsewhere"
    #it says what is missing rather than queueing something that cannot carry on
    card.find_element("css selector", "[data-up-place]").click()
    wait_until(lambda: "where the comic is up to" in card.find_element("css selector", "[data-up-msg]").text)
    card.find_element("css selector", '[data-f="last_url"]').send_keys(SITE + "/comic/6")
    card.find_element("css selector", "[data-up-place]").click()
    wait_until(lambda: "Queued" in browser.find_element("id", "up-msg").text)
    assert page.wait_idle()
    folder = library / "Uncompressed" / "From Elsewhere"
    assert read_meta(folder)["settings"]["url"] == SITE + "/comic/6"
    wait_until(lambda: "From Elsewhere" in browser.find_element("id", "history").text,
               why="Recent never showed the upload")
    #the first try was refused on purpose, which chrome logs as a failed request; only a script error counts
    scripts = [entry for entry in console_errors(browser) if entry.get("source") != "network"]
    assert not scripts, scripts


def test_only_a_zip_is_taken(page):
    #a form post is what a page on another site could make a browser send
    assert upload(page, archive(pages(2)), "x.zip", "text/plain")[0] == 415
    assert upload(page, archive(pages(2)), "x.rar")[0] == 415
    assert upload(page, b"not a zip at all", "x.zip")[0] == 400
