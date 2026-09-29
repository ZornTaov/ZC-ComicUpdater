#what a scrape names a page: what the site says it is called, never with .png tacked on; a page saved the
#old way swapping to the new spelling rather than being held twice; and a comic scraped from its first page
#keeping its record of which page is which as it goes.
import json
import os
import zipfile

import pytest

from conftest import Comic, comic_page, pages_in, read_meta, run

pytestmark = [pytest.mark.browser, pytest.mark.slow]
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 "
JPEG = b"\xff\xd8\xff\xe0" + b"a jpeg"


class Tokened(Comic):
    #every image served from an address that names nothing - /comic-image/<id>/?token=... - the way some
    #sites hand them out. /p/N sends a Content-Disposition naming the file; /q/N sends only its type
    pages = 3

    def page(self, number):
        onward = "/{0}/{1}".format(self.kind, number + 1) if number < self.pages else None
        return comic_page("/comic-image/{0}{1}/?token=abc{1}&expires=99".format(self.kind, number), onward)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/comic-image/"):
            ident = path.strip("/").split("/")[-1]
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            if ident.startswith("p"):
                self.send_header("Content-Disposition", 'inline; filename="page-{0}.webp"'.format(ident[1:]))
            body = WEBP + ident.encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        kind, _, number = path.strip("/").partition("/")
        if kind in ("p", "q") and number.isdigit():
            self.kind = kind
            self.send(self.page(int(number)))
            return
        self.send_error(404)


class Jpegs(Comic):
    #an ordinary comic of jpgs, which scrapes before this change saved as name.jpg.png
    pages = 3

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < self.pages else None
        return comic_page("/img/p{0}.jpg".format(number), onward)

    def image(self, name):
        return JPEG + name.encode()


def scrape(tmp_path, out, url, *extra):
    return run("mirror_base.py", "-o", out, *extra, url, cwd=tmp_path, timeout=240)


def test_the_servers_filename_is_the_name_a_page_is_saved_under(tmp_path, serve):
    site = serve(Tokened)
    out = tmp_path / "Named"
    done = scrape(tmp_path, out, site + "/p/1", "--no-keep-index")
    assert done.returncode == 0, done.stdout[-400:]
    assert pages_in(out, ".webp") == ["page-1.webp", "page-2.webp", "page-3.webp"], os.listdir(out)
    assert not [name for name in os.listdir(out) if "token" in name or name.endswith(".png")], os.listdir(out)


def test_with_no_filename_the_address_names_it_and_the_type_says_what_it_is(tmp_path, serve):
    site = serve(Tokened)
    out = tmp_path / "Typed"
    done = scrape(tmp_path, out, site + "/q/1", "-p", "--no-keep-index")
    assert done.returncode == 0, done.stdout[-400:]
    assert pages_in(out, ".webp") == ["0001_q1.webp", "0002_q2.webp", "0003_q3.webp"], os.listdir(out)


def test_a_jpg_is_saved_as_a_jpg(tmp_path, serve):
    site = serve(Jpegs)
    out = tmp_path / "Plain"
    done = scrape(tmp_path, out, site + "/p/1", "--no-keep-index")
    assert done.returncode == 0, done.stdout[-400:]
    assert pages_in(out, ".jpg") == ["p1.jpg", "p2.jpg", "p3.jpg"], os.listdir(out)
    with zipfile.ZipFile(str(tmp_path / "Plain.cbz")) as zf:
        assert sorted(name for name in zf.namelist() if name.endswith(".jpg")) == ["p1.jpg", "p2.jpg", "p3.jpg"]


def test_a_page_saved_the_old_way_is_held_once_under_its_new_name(tmp_path, serve):
    #a comic with no numbers, scraped before this change: its pages are name.jpg.png. a resume re-saves the
    #page it starts on, now as name.jpg, and the old spelling goes rather than the page being held twice -
    #in the folder and in the archive
    site = serve(Jpegs)
    out = tmp_path / "Legacy"
    out.mkdir()
    for n in (1, 2):
        (out / "p{0}.jpg.png".format(n)).write_bytes(JPEG + "p{0}.jpg".format(n).encode())
    with zipfile.ZipFile(str(tmp_path / "Legacy.cbz"), "w") as zf:
        for n in (1, 2):
            zf.write(str(out / "p{0}.jpg.png".format(n)), "p{0}.jpg.png".format(n))
    done = scrape(tmp_path, out, site + "/p/2", "--no-keep-index")
    assert done.returncode == 0, done.stdout[-400:]
    held = sorted(name for name in os.listdir(out) if name != "mirror_metadata.json")
    assert held == ["p1.jpg.png", "p2.jpg", "p3.jpg"], "page 2 is held once, under its new name: {0}".format(held)
    with zipfile.ZipFile(str(tmp_path / "Legacy.cbz")) as zf:
        packed = sorted(name for name in zf.namelist() if name != "mirror_metadata.json")
    assert packed == ["p1.jpg.png", "p2.jpg", "p3.jpg"], packed


def test_a_comic_scraped_from_its_first_page_keeps_its_index_as_it_goes(tmp_path, serve, config):
    site = serve(Jpegs)
    out = tmp_path / "Fresh"
    done = scrape(tmp_path, out, site + "/p/1", "-p")
    assert done.returncode == 0, done.stdout[-400:]
    named = read_meta(out)["history"].get("index_cache")
    assert named, "the metadata does not name an index"
    with open(str(config / "index" / named), encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    #the names it actually saved, and the sizes they really are - nothing guessed
    assert [(line["n"], line["file"]) for line in lines] == \
        [(1, "0001_p1.jpg"), (2, "0002_p2.jpg"), (3, "0003_p3.jpg")], lines
    assert all(line["bytes"] == os.path.getsize(str(out / line["file"])) for line in lines), lines


def test_no_index_is_started_part_way_in_or_when_told_not_to(tmp_path, serve, config):
    site = serve(Jpegs)
    #part way in: page one of a record begun here would not be the comic's page one
    scrape(tmp_path, tmp_path / "Middle", site + "/p/2", "-p", "-i", "2")
    #told not to
    scrape(tmp_path, tmp_path / "Declined", site + "/p/1", "-p", "--no-keep-index")
    for out in ("Middle", "Declined"):
        assert not read_meta(tmp_path / out)["history"].get("index_cache"), out
    assert not os.listdir(str(config / "index")), os.listdir(str(config / "index"))


class Flaky(Jpegs):
    #five pages whose third image fails until the site is told to mend it, the way a run dies part way
    pages = 5
    broken = True

    def image(self, name):
        if name == "p3.jpg" and Flaky.broken:
            raise ConnectionError("the third image will not come")
        return super().image(name)

    def do_GET(self):
        try:
            Comic.do_GET(self)
        except ConnectionError:
            self.send_error(500)


def index_lines(config, folder):
    named = read_meta(folder)["history"].get("index_cache")
    assert named, "the metadata does not name an index"
    with open(str(config / "index" / named), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def resume(tmp_path, folder):
    #the next run, the way update_comics starts it: the command rebuilt from the comic's own settings
    from comiclib.metadata import settings_to_argv
    return run("mirror_base.py", *settings_to_argv(read_meta(folder)["settings"]), cwd=tmp_path, timeout=240)


def test_a_first_run_that_dies_part_way_has_its_index_carried_on_by_the_next(tmp_path, serve, config):
    Flaky.broken = True
    site = serve(Flaky)
    out = tmp_path / "Stopped"
    done = scrape(tmp_path, out, site + "/p/1", "-p")
    assert done.returncode == 4, "the first run should die at the third page: {0}".format(done.stdout[-300:])
    assert [line["file"] for line in index_lines(config, out)] == ["0001_p1.jpg", "0002_p2.jpg"]
    Flaky.broken = False
    done = resume(tmp_path, out)
    assert done.returncode == 0, done.stdout[-400:]
    lines = index_lines(config, out)
    #every page once, in order, numbered from one with no gap and no repeat where the two runs meet
    assert [(line["n"], line["file"]) for line in lines] == \
        [(n, "{0:04d}_p{0}.jpg".format(n)) for n in range(1, 6)], lines


def test_an_index_line_cut_off_by_a_kill_is_mended_and_the_index_carried_on(tmp_path, serve, config):
    #a run killed outright - a timeout - can stop part way through writing a line. the next run has to mend
    #the end of the file and carry on, not find it unreadable and quietly stop keeping it for good
    Flaky.broken = True
    site = serve(Flaky)
    out = tmp_path / "Killed"
    scrape(tmp_path, out, site + "/p/1", "-p")
    named = read_meta(out)["history"]["index_cache"]
    with open(str(config / "index" / named), "a", encoding="utf-8") as f:
        f.write('{"n": 3, "url": "http://127.0.0.1/p/3", "src": "htt')
    Flaky.broken = False
    done = resume(tmp_path, out)
    assert done.returncode == 0, done.stdout[-400:]
    lines = index_lines(config, out)
    assert [(line["n"], line["file"]) for line in lines] == \
        [(n, "{0:04d}_p{0}.jpg".format(n)) for n in range(1, 6)], lines


def test_half_a_page_left_by_a_killed_run_goes_and_never_reaches_the_archive(tmp_path, serve):
    #a comic without --prefix, stopped while writing its third page: the next run clears what was left and
    #carries on, rather than taking it for a different page under the same name and stopping for good
    site = serve(Jpegs)
    out = tmp_path / "Halfway"
    scrape(tmp_path, out, site + "/p/1", "--no-keep-index")
    (out / "p3.jpg").unlink()
    (out / "p3.jpg.writing").write_bytes(JPEG[:3])
    done = resume(tmp_path, out)
    assert done.returncode == 0, done.stdout[-400:]
    assert "half a page left by a run that was stopped" in done.stdout, done.stdout[-400:]
    assert sorted(os.listdir(str(out))) == ["mirror_metadata.json", "p1.jpg", "p2.jpg", "p3.jpg"]
    with zipfile.ZipFile(str(tmp_path / "Halfway.cbz")) as zf:
        assert not [name for name in zf.namelist() if name.endswith(".writing")], zf.namelist()


def test_starting_a_comic_over_needs_only_its_pages_and_archive_deleted(tmp_path, serve, config):
    #a comic scraped, then deleted and started again from its first page: the index and the alignment left
    #from its first life are moved aside, not added to, and nothing in the config folder had to be touched
    site = serve(Jpegs)
    out = tmp_path / "Again"
    scrape(tmp_path, out, site + "/p/1", "-p", "--prime")
    named = read_meta(out)["history"]["index_cache"]
    (config / "index" / named.replace(".jsonl", ".align.json")).write_text("{}", encoding="utf-8")
    for leftover in list(out.iterdir()):
        leftover.unlink()
    (tmp_path / "Again.cbz").unlink()

    done = scrape(tmp_path, out, site + "/p/1", "-p")
    assert done.returncode == 0, done.stdout[-400:]
    assert "left from before this folder was started over" in done.stdout, done.stdout[-500:]
    assert read_meta(out)["history"]["index_cache"] == named, "the same name, for a fresh record"
    #this run's pages alone, numbered from one - not page one twice
    assert [(line["n"], line["file"]) for line in index_lines(config, out)] == \
        [(n, "{0:04d}_p{0}.jpg".format(n)) for n in range(1, 4)]
    aside = sorted(name for name in os.listdir(str(config / "index")) if ".replaced-" in name)
    assert len(aside) == 2 and aside[0].endswith(".align.json") and aside[1].endswith(".jsonl"), aside


def test_a_walk_or_a_check_starts_no_index_of_its_own(tmp_path, serve, config):
    #both start at a comic's first page with nothing saved, which is what a fresh scrape looks like - but
    #neither saves a page, and a check from the web page must not leave a file behind every time
    site = serve(Jpegs)
    walked = config / "index" / "walk.jsonl"
    run("mirror_base.py", "--index", walked, site + "/p/1", cwd=tmp_path, timeout=240)
    run("mirror_base.py", "--check", site + "/p/1", cwd=tmp_path, timeout=240)
    assert os.listdir(str(config / "index")) == ["walk.jsonl"], os.listdir(str(config / "index"))
