#where a run says to carry on from when it ends somewhere that is not a page of the comic: the front page a
#last next button leads to, a comic that wraps round to its own beginning, and a page that broke.
import pytest

from conftest import Comic, comic_page, pages_in, read_meta, run, write_meta

PAGES = 5
pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Ending(Comic):
    #/p/N is a comic whose last page leads to the front page; /w/N wraps round to its own first page; and
    #/b/N has a third page whose image will not download
    pages = PAGES

    def do_GET(self):
        path = self.path
        if path.startswith("/img/"):
            if path.endswith("broken.png"):
                self.send_error(500)
            else:
                self.send(self.png, "image/png")
            return
        if path == "/":
            #the front page: an image, but not a page of the comic
            self.send('<html><head><title>Front</title></head><body>'
                      '<img class="splash" src="/img/front.png" width="240" height="240">'
                      '<a rel="next" href="/p/1">Start reading</a></body></html>')
            return
        kind, _, number = path.lstrip("/").partition("/")
        if kind not in ("p", "w", "b") or not number.isdigit():
            self.send_error(404)
            return
        number = int(number)
        if number < PAGES:
            onward = "/{0}/{1}".format(kind, number + 1)
        else:
            onward = "/w/1" if kind == "w" else "/"
        name = "broken" if kind == "b" and number == 3 else "{0:04d}".format(number)
        self.send(comic_page("/img/{0}.png".format(name), onward, "Comic {0}".format(number)))


@pytest.fixture
def site(serve):
    return serve(Ending)


def scrape(tmp_path, url, *extra):
    out = tmp_path / "comic"
    done = run("mirror_base.py", "-o", out, "--no-cbz", "-p", *extra, url, cwd=tmp_path)
    return out, done


def test_a_last_page_leading_to_the_front_page_ends_the_run_there(tmp_path, site):
    out, done = scrape(tmp_path, site + "/p/1")
    meta = read_meta(out)
    assert len(pages_in(out)) == PAGES
    assert done.returncode == 0, done.stdout[-300:]
    assert "has no page of the comic on it, so this is as far as the comic goes for now" in done.stdout
    #reaching the latest page is not the comic having finished: that is the reader's call
    assert "end of the comic" not in done.stdout and "has ended" not in done.stdout
    #the front page is not where the next run should start, nor is the number moved past the last page
    assert meta["settings"]["url"] == site + "/p/{0}".format(PAGES)
    assert meta["settings"]["increment"] == PAGES
    assert meta["state"]["completed"] is True
    assert meta["history"]["runs"][-1]["stop_reason"] == "the next link led off the comic"


def test_a_comic_that_wraps_round_is_not_resumed_from_page_one(tmp_path, site):
    out, done = scrape(tmp_path, site + "/w/1")
    settings = read_meta(out)["settings"]
    assert "looped" in done.stdout
    assert settings["url"].endswith("/w/{0}".format(PAGES))
    assert settings["increment"] == PAGES


def test_a_page_that_will_not_download_is_where_the_next_run_starts(tmp_path, site):
    out, done = scrape(tmp_path, site + "/b/1")
    settings = read_meta(out)["settings"]
    assert pages_in(out) == ["0001_0001.png", "0002_0002.png"]
    assert done.returncode == 4, done.stdout[-200:]
    #the page that failed, counted as the one after the last saved, rather than the one before it
    assert settings["url"].endswith("/b/3")
    assert settings["increment"] == 3


def test_a_first_page_with_no_comic_image_is_a_fault_not_an_ending(tmp_path, site):
    out, done = scrape(tmp_path, site + "/")
    assert done.returncode == 3, done.stdout[-200:]
    assert "not stored" in done.stdout
    assert not out.exists() or not pages_in(out)


def test_priming_resumes_on_the_page_after_the_first(tmp_path, site):
    out, done = scrape(tmp_path, site + "/p/1", "--prime")
    settings = read_meta(out)["settings"]
    assert len(pages_in(out)) == 1
    assert settings["url"].endswith("/p/2")
    assert settings["increment"] == 2


def test_whether_a_comic_has_ended_is_only_ever_the_readers_call(tmp_path, site):
    out, _ = scrape(tmp_path, site + "/p/1")
    meta = read_meta(out)
    #the run got to the latest page, and that is all it says
    assert meta["settings"]["ended"] is False
    assert meta["state"]["completed"] is True
    meta["settings"]["ended"] = True
    write_meta(out, meta)
    #scraped again, as update_comics would if told to: the mark is the reader's and survives
    run("mirror_base.py", "-o", out, "--no-cbz", "-p", site + "/p/1", cwd=tmp_path)
    assert read_meta(out)["settings"]["ended"] is True
