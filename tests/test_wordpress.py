#reading which page is which from a WordPress site's list of its posts, instead of walking it. the fake site
#answers /wp-json/ the way WordPress does: a comic post type, a hundred posts an answer, the image each
#features in the media list. the folder was saved by another tool counting from 0000.png, and keeps its
#weekly extras somewhere else, so the list holds pages the folder does not - as a real one does.
import json
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import Site, read_meta, run, write_meta

POSTS = 150
#every seventh post is a weekly extra the folder keeps elsewhere
EXTRA = {n for n in range(1, POSTS + 1) if n % 7 == 0}


def jpeg(n):
    #a jpeg's first bytes, and a size no other page shares, which is what lines a renamed file up
    return b"\xff\xd8\xff\xe0" + bytes([n % 251]) * (1000 + n)


def post(n, base):
    #ids count up in the order posts were made. posts 2 and 3 share a date, and the api breaks that tie
    #however the database likes, so only the id puts them in the order they were made
    when = datetime(2003, 1, 1) + timedelta(hours=2 if n == 3 else n)
    return {"id": 1000 + n, "date": when.strftime("%Y-%m-%dT%H:%M:%S"), "slug": "page-{0}".format(n),
            "link": "{0}/comic/page-{1}/".format(base, n), "title": {"rendered": "Page {0} &amp; more".format(n)},
            #post 5 features nothing and carries its page in its body, as older comic themes did
            "featured_media": 0 if n == 5 else 5000 + n,
            "content": {"rendered": '<p><img class="x" src="{0}/img/strip{1:03d}.jpeg?v=2"></p>'.format(base, n)}}


class WordPress(Site):
    #a 429 the first time each of these images is asked about, and its size the second
    busy_once = {"strip010.jpeg", "strip011.jpeg"}
    asked = set()

    def base(self):
        return "http://{0}".format(self.headers["Host"])

    def posts(self):
        return [post(n, self.base()) for n in range(1, POSTS + 1)]

    def json(self, body, extra=None):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=UTF-8")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def pick(self, items, query):
        #what _fields asks for and nothing else, as the api does
        fields = query.get("_fields", [""])[0].split(",")
        return [{key: item[key] for key in fields if key in item} for item in items]

    def answer(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path == "/wp-json/":
            return self.json({"name": "A Comic", "namespaces": ["wp/v2"]})
        if path == "/wp-json/wp/v2/types":
            return self.json({"post": {"slug": "post", "rest_base": "posts"},
                              "page": {"slug": "page", "rest_base": "pages"},
                              "attachment": {"slug": "attachment", "rest_base": "media"},
                              "comic": {"slug": "comic", "rest_base": "comic"}})
        if path == "/wp-json/wp/v2/posts":
            return self.json([])
        if path == "/wp-json/wp/v2/comic":
            posts = self.posts()
            if "slug" in query:
                return self.json(self.pick([p for p in posts if p["slug"] == query["slug"][0]], query))
            if "include" in query:
                wanted = {int(one) for one in query["include"][0].split(",")}
                return self.json(self.pick([p for p in posts if p["id"] in wanted], query))
            #the database's own order: by id, which is not quite the date order
            posts.sort(key=lambda p: p["id"] if p["id"] not in (1002, 1003) else 2003 - p["id"])
            size = int(query.get("per_page", ["10"])[0])
            page = int(query.get("page", ["1"])[0])
            pages = -(-len(posts) // size)
            return self.json(self.pick(posts[(page - 1) * size:page * size], query),
                             {"X-WP-Total": str(len(posts)), "X-WP-TotalPages": str(pages)})
        if path == "/wp-json/wp/v2/media":
            wanted = {int(one) for one in query["include"][0].split(",")}
            return self.json([{"id": 5000 + n, "source_url": "{0}/img/strip{1:03d}.jpeg".format(self.base(), n)}
                              for n in range(1, POSTS + 1) if 5000 + n in wanted])
        if path.startswith("/img/strip"):
            name = path.rsplit("/", 1)[-1]
            if name in self.busy_once and name not in self.asked:
                self.asked.add(name)
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = jpeg(int(name[5:8]))
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        self.send_error(404)

    def do_GET(self):
        self.answer()

    def do_HEAD(self):
        self.answer()


class Reposted(WordPress):
    #page 40 posted a second time on the same date under /page-40-2/, featuring the very same image
    def posts(self):
        again = dict(post(40, self.base()), id=2000, slug="page-40-2",
                     link="{0}/comic/page-40-2/".format(self.base()))
        return super().posts() + [again]


class NotWordPress(Site):
    def do_GET(self):
        self.send("<html><body>a comic on a hand-built site</body></html>")


@pytest.fixture
def comic(library, chapters, serve):
    base = serve(WordPress)
    folder = library / "Uncompressed" / "Weekly"
    folder.mkdir()
    #counted from 0000.png by the other tool, skipping every weekly extra
    for count, n in enumerate(n for n in range(1, POSTS + 1) if n not in EXTRA):
        (folder / "{0:04d}.png".format(count)).write_bytes(jpeg(n))
    write_meta(folder, {"schema": 2, "settings": {"url": base + "/comic/page-3/", "output": "Uncompressed/Weekly"},
                        "history": {"runs": []}})
    return base, folder, chapters.index_path(str(folder))


def lines(cache):
    with open(cache, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_the_list_of_posts_is_the_index(comic, library):
    base, folder, cache = comic
    done = run("chapters.py", "index", folder, "--wordpress", "--root", library)
    held = lines(cache)
    assert len(held) == POSTS, done.stdout[-1500:]
    #in date order, a tie broken by the order the posts were made, whatever order the api answered in
    assert [line["url"] for line in held[:4]] == ["{0}/comic/page-{1}/".format(base, n) for n in (1, 2, 3, 4)]
    assert held[0]["n"] == 1 and held[-1]["n"] == POSTS
    assert held[0]["title"] == "Page 1 & more"
    assert held[0]["file"] == "strip001.jpeg"
    #a post featuring nothing is read for the image in its body
    assert held[4]["src"] == base + "/img/strip005.jpeg?v=2" and held[4]["file"] == "strip005.jpeg"
    #and every image's size was asked for, the two that asked for a pause first included
    assert all(line["bytes"] == len(jpeg(line["n"])) for line in held), [l for l in held if not l["bytes"]][:3]
    assert "asked for a pause" in done.stdout


def test_it_lines_up_a_folder_counted_from_nought(comic, library):
    base, folder, cache = comic
    done = run("chapters.py", "index", folder, "--wordpress", "--root", library)
    assert done.returncode == 0, done.stdout[-1500:]
    assert "settled" in done.stdout
    aligned = json.load(open(cache.replace(".jsonl", ".align.json"), encoding="utf-8"))
    files = {page["n"]: page["file"] for page in aligned["pages"]}
    assert files[1] == "0000.png" and files[8] == "0006.png"
    #the weekly extras are pages this folder does not have, not a reason to refuse
    assert [n for n, name in files.items() if name is None] == sorted(EXTRA)
    assert len(read_meta(folder)["history"]["gaps"]) == len(EXTRA)


def test_renumbering_by_the_sites_names(comic, library):
    base, folder, cache = comic
    run("chapters.py", "index", folder, "--wordpress", "--root", library)
    #a page the other tool saved as a png holding png bytes, which the site now serves as a jpeg
    (folder / "0001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1002)
    done = run("chapters.py", "renumber", folder, "--site-names", "--root", library, "--force")
    assert done.returncode == 0, done.stdout[-1500:]
    names = sorted(os.listdir(str(folder)))
    assert "0001_strip001.jpeg" in names
    assert "0002_strip002.png" in names
    #page 7 is a weekly extra this folder does not have, so no file takes its number
    assert "0008_strip008.jpeg" in names and not any(name.startswith("0007_") for name in names)
    assert all(name[:5].rstrip("_").isdigit() and name[4] == "_" for name in names if name != "mirror_metadata.json")
    assert read_meta(folder)["settings"]["prefix"] is True


def test_an_index_already_there_is_not_written_over(comic, library):
    base, folder, cache = comic
    with open(cache, "w", encoding="utf-8") as f:
        f.write(json.dumps({"n": 1, "url": "walked", "src": None, "file": None, "title": "", "bytes": None}) + "\n")
    done = run("chapters.py", "index", folder, "--wordpress", "--root", library)
    assert done.returncode == 2 and "--restart" in done.stdout
    assert len(lines(cache)) == 1
    done = run("chapters.py", "index", folder, "--wordpress", "--restart", "--root", library)
    assert len(lines(cache)) == POSTS, done.stdout[-1500:]
    #the old one is set aside, not deleted
    assert any(".replaced-" in name for name in os.listdir(os.path.dirname(cache)))


def test_one_image_posted_twice_is_one_page(library, chapters, serve):
    base = serve(Reposted)
    folder = library / "Uncompressed" / "Reposted"
    folder.mkdir()
    for n in range(1, POSTS + 1):
        (folder / "{0:04d}.png".format(n)).write_bytes(jpeg(n))
    done = run("chapters.py", "index", folder, "--wordpress", "--start", base + "/comic/page-1/", "--root", library)
    assert "Left out 1 post(s)" in done.stdout, done.stdout[-1500:]
    held = lines(chapters.index_path(str(folder)))
    assert len(held) == POSTS
    assert not any(line["url"].endswith("/page-40-2/") for line in held)
    assert done.returncode == 0 and "settled" in done.stdout


def test_a_size_two_pages_share_still_anchors_between_its_neighbours(tmp_path, chapters):
    #pages 3 and 9 happen to be exactly the same size, so neither is unique across the comic; each sits next
    #to a page this folder does not have, so counting alone cannot place them either
    sizes = {1: 100, 2: 200, 3: 777, 4: 400, 5: 500, 6: 600, 7: 700, 8: 800, 9: 777, 10: 1000, 11: 1100}
    missing = {4, 10}
    pages = [{"n": n, "url": "u{0}".format(n), "src": None, "file": None, "bytes": size} for n, size in sizes.items()]
    files = []
    for n, size in sizes.items():
        if n not in missing:
            name = "{0:04d}.png".format(len(files))
            (tmp_path / name).write_bytes(b"x" * size)
            files.append(name)
    aligned, how, anchors, trouble = chapters.align(pages, files, str(tmp_path))
    assert not trouble
    assert aligned[2] == "0002.png" and aligned[8] == "0007.png"
    assert aligned[3] is None and aligned[9] is None


def test_a_site_that_is_not_wordpress_says_to_walk(library, chapters, serve):
    base = serve(NotWordPress)
    folder = library / "Uncompressed" / "Handmade"
    folder.mkdir()
    (folder / "0001.png").write_bytes(jpeg(1))
    done = run("chapters.py", "index", folder, "--wordpress", "--start", base + "/comic/1/", "--root", library)
    assert done.returncode == 2
    assert "Walk it instead" in done.stdout
    assert not os.path.exists(chapters.index_path(str(folder)))
