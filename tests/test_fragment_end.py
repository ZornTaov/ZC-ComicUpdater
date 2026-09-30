#a comic whose newest page links "next" to its own address with a '#' on the end. compared as text that is
#a page after the newest, so it was saved a second time, counted as a page of its own - every run after
#numbering the comic one further out - and a walk recorded it as a page no file belongs to, so the comic
#could not be lined up. an address that differs only after the '#' and shows the same image is the same
#page. a comic that routes every page by the fragment, drawn by javascript, is still read to the end.
import json

import pytest

from conftest import Comic, comic_page, pages_in, read_meta, run

PAGES = 5
pytestmark = [pytest.mark.browser, pytest.mark.slow]


class Anchored(Comic):
    #/p/N, whose newest page's next link is /p/N# - or /p/N#comic, an anchor on the page itself
    pages = PAGES
    tail = "#"

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < PAGES else "/p/{0}{1}".format(number, self.tail)
        return comic_page("/img/{0:04d}.png".format(number), onward, "Comic {0}".format(number))


class NamedAnchor(Anchored):
    tail = "#comic"


class Routed(Comic):
    #one document at /app whose script draws page N for #/page/N, the way a comic built by javascript
    #routes its pages. every address differs only after the '#', and every page shows a different image -
    #drawn a moment after the address changes, as a page the script has to fetch first is, so for that
    #moment the new address still shows the old page's picture
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(self.png, "image/png")
            return
        if self.path.split("#")[0] != "/app":
            self.send_error(404)
            return
        self.send("""<html><head><title>Comic</title></head><body><div id="wrap">
<img id="cc-comic" width="240" height="240"></div><a id="next" rel="next">Next</a>
<script>
function draw() {
  var n = parseInt((location.hash.match(/(\\d+)$/) || [0, 1])[1], 10);
  document.getElementById("cc-comic").src = "/img/" + ("000" + n).slice(-4) + ".png";
  var next = document.getElementById("next");
  if (n < %d) { next.href = "#/page/" + (n + 1); } else { next.parentNode.removeChild(next); }
}
window.addEventListener("hashchange", function () { setTimeout(draw, 1500); });
draw();
</script></body></html>""" % PAGES)


def scrape(tmp_path, url, *extra):
    out = tmp_path / "comic"
    done = run("mirror_base.py", "-o", out, "--no-cbz", *extra, url, cwd=tmp_path)
    return out, done


@pytest.mark.parametrize("site_kind", [Anchored, NamedAnchor], ids=["bare-hash", "anchor"])
def test_a_next_link_to_the_same_page_with_a_hash_is_the_end(tmp_path, serve, site_kind):
    site = serve(site_kind)
    out, done = scrape(tmp_path, site + "/p/1")
    assert done.returncode == 0, done.stdout[-400:]
    assert "goes to the same page" in done.stdout, done.stdout[-400:]
    meta = read_meta(out)
    #counted as the five pages it is, and carried on from the newest one as the site addresses it
    assert meta["history"]["runs"][-1]["pages_saved"] == PAGES, meta["history"]["runs"][-1]
    assert meta["settings"]["increment"] == PAGES, meta["settings"]
    assert meta["settings"]["url"] == site + "/p/{0}".format(PAGES), meta["settings"]
    assert len(pages_in(out)) == PAGES

    #and the next run, starting there, finds nothing new rather than one more page
    out, done = scrape(tmp_path, meta["settings"]["url"], "-i", str(PAGES))
    meta = read_meta(out)
    assert meta["settings"]["increment"] == PAGES, meta["settings"]


def test_a_walk_does_not_record_the_same_page_with_a_hash_as_another(tmp_path, serve):
    site = serve(Anchored)
    index = tmp_path / "walk.jsonl"
    done = run("mirror_base.py", "--index", index, site + "/p/1", cwd=tmp_path)
    assert done.returncode == 0, done.stdout[-400:]
    with open(str(index), encoding="utf-8") as f:
        lines = [json.loads(text) for text in f if text.strip()]
    assert [line["url"].rsplit("/", 1)[-1] for line in lines] == [str(n) for n in range(1, PAGES + 1)], lines[-2:]


def test_a_comic_routed_by_the_fragment_is_read_to_the_end(tmp_path, serve):
    site = serve(Routed)
    out, done = scrape(tmp_path, site + "/app#/page/1", "--enable_javascript")
    assert done.returncode == 0, done.stdout[-400:]
    assert pages_in(out) == ["{0:04d}.png".format(n) for n in range(1, PAGES + 1)], done.stdout[-400:]
