#a page the comic has and the site does not: found elsewhere and put in the folder, where no walk can ever
#see it. until someone says so it looks like a stray and keeps the comic from settling; once it is marked
#as recovered it lines up, packs where it reads, and can be taken back.
import os
import time
import zipfile

import pytest

from conftest import run, write_index, write_meta

#a comic of two chapters, five pages each. the site has lost chapter 1's page 3 entirely
LOST = "toy_p13.png"


@pytest.fixture
def toy(library, chapters):
    folder = library / "Uncompressed" / "Toy"
    folder.mkdir()
    urls, names = [], []
    for chapter in (1, 2):
        for p in range(1, 6):
            if chapter == 1 and p == 3:
                continue
            urls.append("https://x.test/c/issue-{0}-page-{1}/".format(chapter, p))
            names.append("toy_p{0}{1}.png".format(chapter, p))
    order = names[:2] + [LOST] + names[2:]
    for at, name in enumerate(order):
        path = folder / name
        path.write_bytes(bytes([at % 251]) * (300 + at))
        stamp = time.time() - (len(order) - at) * 10
        os.utime(str(path), (stamp, stamp))
    write_meta(folder, {"settings": {"url": urls[-1], "cbz_path": "CBZs/Toy/Toy.cbz"}, "history": {}})
    write_index(chapters.index_path(str(folder), str(library), None),
                [{"n": at, "url": url, "src": "https://x.test/i/" + names[at - 1], "image": names[at - 1],
                  "bytes": os.path.getsize(str(folder / names[at - 1]))} for at, url in enumerate(urls, 1)])
    return folder


def ch(command, folder, *more):
    done = run("chapters.py", command, folder, *more)
    return done.returncode, done.stdout + done.stderr


def mark(folder):
    return ch("recovered", folder, "--file", LOST, "--note", "found on the artist's own page")


def test_before_anyone_says_so_the_recovered_page_looks_like_a_stray(toy, library):
    code, out = ch("align", toy, "--root", library)
    assert "1 file(s) no page claims" in out, [l for l in out.splitlines() if "claims" in l]
    assert "NOT settled" in out, out.strip().splitlines()[-2:]
    #and it says how to put that right
    assert "chapters.py recovered" in out, [l for l in out.splitlines() if "recovered" in l]


def test_a_page_marked_recovered_is_noted_and_listed(toy):
    code, out = mark(toy)
    assert code == 0 and "is a page this comic has and the site does not" in out, out.strip().splitlines()[:2]
    code, out = ch("recovered", toy)
    assert LOST in out and "artist's own page" in out, out.strip().splitlines()


def test_once_marked_the_comic_lines_up(toy, library):
    mark(toy)
    code, out = ch("align", toy, "--root", library)
    assert code == 0 and "settled" in out and "NOT settled" not in out, out.strip().splitlines()[-2:]
    assert "the site no longer serves, put back by hand" in out, \
        [l for l in out.splitlines() if "by hand" in l]
    assert "no page claims" not in out, "it is still called a stray"


def test_chaptering_and_packing_keep_it_where_it_reads(toy, library):
    mark(toy)
    ch("align", toy, "--root", library)
    code, out = ch("chapters", toy, "--root", library, "--urls", "--save")
    assert "2 chapter(s)" in out, [l for l in out.splitlines() if "chapter(s) over" in l]
    code, out = ch("pack", toy, "--root", library)
    assert code == 0 and "2 chapter archive(s)" in out, out.strip().splitlines()[-2:]
    assert "all 10 page(s) are in exactly one chapter archive" in out, out.strip().splitlines()[-1:]
    #and it says where the recovered page went
    assert "put back by hand, kept where they read" in out, [l for l in out.splitlines() if "kept where" in l]
    shelf = library / "CBZs" / "Toy"
    first = sorted(f for f in os.listdir(str(shelf)) if f.endswith(".cbz"))[0]
    with zipfile.ZipFile(str(shelf / first)) as z:
        inside = [n for n in z.namelist() if not n.endswith(".xml")]
    assert LOST in inside, inside
    assert inside.index(LOST) == 2, inside


def test_forgetting_it_makes_it_a_stray_again(toy, library):
    mark(toy)
    code, out = ch("recovered", toy, "--file", LOST, "--forget")
    assert code == 0 and "forgotten" in out, out.strip().splitlines()[:1]
    code, out = ch("align", toy, "--root", library)
    assert "1 file(s) no page claims" in out, [l for l in out.splitlines() if "claims" in l]


def test_a_name_that_is_not_in_the_folder_is_refused(toy):
    code, out = ch("recovered", toy, "--file", "nothing-here.png")
    assert code == 2 and "is not in" in out, out.strip().splitlines()[:1]
