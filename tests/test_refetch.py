#fetching better copies of pages a library already holds. the site serves big images; the folder holds
#small ones, as a library copied from elsewhere would. page 3's image is gone from the site, and page 4
#answers with fewer bytes than it promised - neither may be written over.
import json
import os
import zipfile

import pytest

from conftest import Site, run, write_index, write_meta

BIG = {1: b"A" * 5000, 2: b"B" * 6000, 4: b"D" * 7000, 5: b"E" * 8000}
SMALL = {1: b"a" * 1000, 2: b"b" * 1200, 3: b"c" * 1300, 4: b"d" * 1400, 5: b"e" * 1500}


class Bigger(Site):
    def do_GET(self):
        n = int(self.path.rsplit("/", 1)[-1].split(".")[0])
        if n not in BIG:
            self.send_error(404)
            return
        #page 4 lies about its size
        body = BIG[n][:20] if n == 4 else BIG[n]
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(BIG[n])))
        self.end_headers()
        self.wfile.write(body)


class Small:
    def __init__(self, library, comic):
        self.library = library
        self.comic = comic
        self.cbz = library / "CBZs" / "Small.cbz"

    def refetch(self, *extra):
        return run("chapters.py", "refetch", self.comic, "--root", self.library, *extra)

    def sizes(self):
        return {n: os.path.getsize(str(self.comic / "{0:04d}.png".format(n))) for n in SMALL}

    def archived(self):
        with zipfile.ZipFile(str(self.cbz)) as zf:
            return {info.filename: info.file_size for info in zf.infolist()}


@pytest.fixture
def small(library, chapters, serve):
    base = serve(Bigger)
    comic = library / "Uncompressed" / "Small"
    comic.mkdir()
    for n, body in SMALL.items():
        (comic / "{0:04d}.png".format(n)).write_bytes(body)
    write_meta(comic, {"schema": 2, "settings": {"url": base + "/p/5", "output": "Uncompressed/Small",
                                                 "cbz_path": "CBZs/Small.cbz", "increment": 5},
                       "history": {"runs": []}})
    cache = chapters.index_path(str(comic))
    #the walk's record says how big each image is on the site; for the one the site lost, it cannot
    write_index(cache, [{"n": n, "url": "{0}/p/{1}".format(base, n), "src": "{0}/img/{1}.png".format(base, n),
                         "file": "{0}.png".format(n), "title": "t", "bytes": len(BIG[n]) if n in BIG else None}
                        for n in sorted(SMALL)])
    with open(cache.replace(".jsonl", ".align.json"), "w") as f:
        json.dump({"comic": str(comic), "settled": True,
                   "pages": [{"n": n, "url": "{0}/p/{1}".format(base, n), "src": "{0}/img/{1}.png".format(base, n),
                              "file": "{0:04d}.png".format(n), "how": "size", "title": "t"} for n in sorted(SMALL)]},
                  f)
    held = Small(library, comic)
    with zipfile.ZipFile(str(held.cbz), "w", zipfile.ZIP_STORED) as zf:
        for n in sorted(SMALL):
            zf.write(str(comic / "{0:04d}.png".format(n)), "Small/{0:04d}.png".format(n))
    return held


def test_a_dry_run_changes_nothing(small):
    before = small.sizes()
    done = small.refetch("--dry-run")
    assert "4 page(s) to fetch again" in done.stdout, done.stdout[:300]
    assert small.sizes() == before


def test_only_pages_that_arrive_whole_are_replaced(small):
    done = small.refetch()
    sizes = small.sizes()
    assert sizes[1] == 5000 and sizes[2] == 6000, sizes
    assert sizes[3] == 1300, "the page the site no longer has was touched: {0}".format(sizes)
    assert sizes[4] == 1400, "the page that arrived short was written over: {0}".format(sizes)
    assert sizes[5] == 8000, sizes
    #the short fetch is named
    assert done.stdout.count("was not replaced") == 1, done.stdout[-400:]
    #page 3 is never attempted, since the site never said how big it is
    assert "page 3 " not in done.stdout, done.stdout[-300:]
    assert not [f for f in os.listdir(str(small.comic)) if f.endswith(".fetching")], os.listdir(str(small.comic))


def test_the_archive_keeps_the_old_copies_until_it_is_repacked(small):
    small.refetch()
    held = small.archived()
    assert held["Small/0001.png"] == 1000, held
    run("chapters.py", "repack", small.comic, "--root", small.library)
    held = small.archived()
    assert held["Small/0001.png"] == 5000 and held["Small/0005.png"] == 8000, held
    #the folder-prefixed layout is kept, and so is the metadata file inside it. the ComicInfo is at the top,
    #where a reader looks for it
    assert all(name.startswith("Small/") for name in held if name != "ComicInfo.xml"), list(held)[:3]
    assert "Small/mirror_metadata.json" in held, list(held)
    assert len([n for n in held if n.endswith(".png")]) == 5, held
    assert not os.path.exists(str(small.cbz) + ".packing")


def test_a_second_run_only_retries_what_is_still_not_right(small):
    small.refetch()
    done = small.refetch()
    assert "1 page(s) to fetch again" in done.stdout, done.stdout[:200]
    #and the short-fetching page is still refused
    assert "Replaced 0 page(s)" in done.stdout, done.stdout[-300:]


def test_all_reaches_for_every_page_but_invents_none(small):
    done = small.refetch("--all", "--dry-run")
    assert "5 page(s) to fetch again" in done.stdout, done.stdout[:200]
    done = small.refetch("--all")
    #the one the site lost is reported, not invented
    assert "was not replaced" in done.stdout, done.stdout[-400:]
    assert small.sizes()[3] == 1300
