#correcting where a chapter starts, by hand: on a comic already packed into chapter archives the correction
#repacks only the chapters it moved, --no-repack leaves them to be done later, a comic with no archives is
#only written down, and a comic whose site says nowhere where its chapters start can be given them one
#boundary at a time.
import os
import shutil
import time
import zipfile

import pytest

from conftest import read_meta, run, write_index, write_meta


@pytest.fixture
def toy(library, chapters):
    #three issues of five pages, the middle one's cover named oddly, as a site does
    folder = library / "Uncompressed" / "Toy"
    folder.mkdir()
    urls, names = [], []
    for issue in (1, 2, 3):
        urls.append("https://x.test/c/{0}-the-odd-one/".format(issue) if issue == 2
                    else "https://x.test/c/issue-{0}-cover/".format(issue))
        names.append("odd.jpg" if issue == 2 else "{0}cover.jpg".format(issue))
        for p in range(1, 5):
            urls.append("https://x.test/c/issue-{0}-page-{1}/".format(issue, p))
            names.append("i{0}p{1}.jpg".format(issue, p))
    for at, name in enumerate(names):
        path = folder / name
        path.write_bytes(bytes([at % 251]) * (200 + at))
        stamp = time.time() - (len(names) - at) * 10
        os.utime(str(path), (stamp, stamp))
    write_meta(folder, {"settings": {"url": urls[-1], "cbz_path": "CBZs/Toy/Toy.cbz"}, "history": {}})
    write_index(chapters.index_path(str(folder), str(library), None),
                [{"n": at + 1, "url": url, "src": "https://x.test/i/" + names[at], "image": names[at],
                  "bytes": 200 + at} for at, url in enumerate(urls)])
    ch(folder, library, "align", "--by-time")
    return folder


def ch(folder, library, command, *more):
    done = run("chapters.py", command, folder, "--root", library, *more)
    return done.returncode, done.stdout + done.stderr


def shelf(library):
    return library / "CBZs" / "Toy"


def stamps(library):
    return {name: os.path.getmtime(str(shelf(library) / name)) for name in os.listdir(str(shelf(library)))}


def held(library, name):
    with zipfile.ZipFile(str(shelf(library) / name)) as z:
        return len([n for n in z.namelist() if not n.endswith('/') and not n.endswith('.xml')])


def chaptered_and_packed(folder, library):
    code, said = ch(folder, library, "chapters", "--urls", "--save")
    packed = ch(folder, library, "pack")
    return said, packed


def test_the_odd_cover_lands_at_the_end_of_the_issue_before(toy, library):
    said, (code, out) = chaptered_and_packed(toy, library)
    assert "3 chapter(s)" in said and "Issue 2" in said, [l for l in said.splitlines() if "Issue" in l]
    assert code == 0 and "3 chapter archive(s)" in out, out.strip().splitlines()[-2:]
    counts = {n: held(library, n) for n in sorted(stamps(library))}
    assert held(library, "Toy - c001 - Issue 1.cbz") == 6, counts
    assert held(library, "Toy - c002 - Issue 2.cbz") == 4, counts


def test_correcting_a_boundary_repacks_only_the_chapters_it_moved(toy, library):
    chaptered_and_packed(toy, library)
    was = stamps(library)
    #the archives' write times are what tell a rewrite apart, and some filesystems keep them to the second
    time.sleep(1.1)
    code, out = ch(toy, library, "fix", "--at", "https://x.test/c/2-the-odd-one/", "--label", "Issue 2")
    assert code == 0, out.strip().splitlines()[-3:]
    #it repacks by itself
    assert "chapter archive(s)" in out, [l for l in out.splitlines() if "wrote" in l or "archive(s)" in l]
    now = stamps(library)
    assert now["Toy - c001 - Issue 1.cbz"] > was["Toy - c001 - Issue 1.cbz"], (was, now)
    assert now["Toy - c002 - Issue 2.cbz"] > was["Toy - c002 - Issue 2.cbz"], (was, now)
    assert now["Toy - c003 - Issue 3.cbz"] == was["Toy - c003 - Issue 3.cbz"], "issue 3 was rewritten"
    #and they now hold the corrected boundary
    counts = {n: held(library, n) for n in sorted(now)}
    assert held(library, "Toy - c001 - Issue 1.cbz") == 5, counts
    assert held(library, "Toy - c002 - Issue 2.cbz") == 5, counts


def no_repack(folder, library):
    chaptered_and_packed(folder, library)
    ch(folder, library, "fix", "--at", "https://x.test/c/2-the-odd-one/", "--label", "Issue 2")
    time.sleep(1.1)
    was = stamps(library)
    code, out = ch(folder, library, "fix", "--at", "3", "--label", "Issue 1", "--no-repack")
    return was, out


def test_no_repack_leaves_the_archives_as_they_were(toy, library):
    was, out = no_repack(toy, library)
    assert "still hold the old boundaries" in out, out.strip().splitlines()[-1:]
    assert stamps(library) == was, "an archive was rewritten"


def test_a_comic_with_no_archives_yet_is_not_packed(toy, library):
    no_repack(toy, library)
    shutil.rmtree(str(shelf(library)))
    meta = read_meta(toy)
    meta["chapters"].pop("packed", None)
    write_meta(toy, meta)
    code, out = ch(toy, library, "fix", "--at", "3", "--label", "Issue 1")
    #it just records the correction
    assert code == 0 and "chapter archive(s)" not in out, out.strip().splitlines()[-2:]
    assert not shelf(library).exists(), "archives were written"


def test_boundaries_set_by_hand_make_chapters_where_the_site_gives_none(toy, library):
    #a comic whose site says nowhere where its chapters start
    code, out = ch(toy, library, "fix", "--at", "1", "--label", "Part One")
    assert code == 0 and "1 chapter(s) over" in out, [l for l in out.splitlines() if "chapter" in l][:3]
    code, out = ch(toy, library, "fix", "--at", "8", "--label", "Part Two")
    assert "2 chapter(s) over" in out, [l for l in out.splitlines() if "chapter(s) over" in l]
    kept = read_meta(toy)["chapters"]
    #both are recorded, and marked as set by hand
    assert [c["label"] for c in kept["list"]] == ["Part One", "Part Two"], kept
    assert kept.get("source") == "hand", kept
    #working them out again keeps them rather than finding nothing
    code, out = ch(toy, library, "chapters")
    assert code == 0 and "set by hand" in out and "2 chapter(s) over" in out, out.strip().splitlines()[:3]
