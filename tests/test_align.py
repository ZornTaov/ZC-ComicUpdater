#lining up the record of a walked comic against the files on disk: by name where a name survives, by order
#between those anchors, and saying so rather than guessing when the counts do not agree. also the order a
#folder's pages are read in, and checking a placement against the sizes the site reports.
import pytest


def walked(names):
    return [{"n": at + 1, "url": "https://x.test/p{0}".format(at + 1), "file": name, "title": "t"}
            for at, name in enumerate(names)]


#a comic whose site names every image, held in a folder where someone renamed the first 731 to plain
#numbers and only the last four still carry the site's names
SITE = ["2005-01-{0:02d}-MC{1:04d}.jpg.png".format(min(at, 28) + 1, at + 1) for at in range(731)] + \
       ["MC_{0:04d}.jpg.png".format(n) for n in range(732, 736)]
HELD = ["{0:04d}.jpg".format(n) for n in range(1, 732)] + \
       ["{0:04d}_MC_{0:04d}.jpg.png".format(n) for n in range(732, 736)]


def test_a_renamed_comic_lines_up_by_order_between_the_names_that_survive(chapters):
    aligned, how, anchors, trouble = chapters.align(walked(SITE), HELD)
    assert all(aligned) and len(aligned) == 735, how.count(None)
    assert len(anchors) == 4, "the four surviving names should anchor it: {0}".format(anchors)
    assert aligned[0] == "0001.jpg"
    assert aligned[-1] == "0735_MC_0735.jpg.png"
    assert how.count("order") == 731
    assert not trouble


def test_a_page_missing_from_disk_is_reported_not_quietly_shifted(chapters):
    short = HELD[:300] + HELD[301:]
    aligned, how, anchors, trouble = chapters.align(walked(SITE), short)
    assert len(trouble) == 1, "the stretch holding the gap should be unresolved: {0}".format(trouble)
    assert trouble[0]["pages"] - trouble[0]["files"] == 1, "it says how far out it is: {0}".format(trouble)
    assert aligned[-1] == "0735_MC_0735.jpg.png", "pages after the anchor still line up"
    assert all(name is None for name in aligned[:731]), \
        "nothing before the gap may be shifted onto the wrong file: {0}".format([n for n in aligned[:731] if n][:3])


def test_a_name_that_appears_twice_is_not_trusted_as_an_anchor(chapters):
    held = ["0001_a.png", "0002_b.png", "0003_b.png", "0004_c.png"]
    aligned, how, anchors, trouble = chapters.align(walked(["a.png", "b.png", "b.png", "c.png"]), held)
    assert len(anchors) == 2, "only the names that appear once anchor: {0}".format(anchors)
    assert aligned == held, "the doubled pair still lines up by order"


def test_a_comic_nobody_renamed_lines_up_entirely_by_name(chapters):
    aligned, how, anchors, trouble = chapters.align(
        walked(SITE[:20]), ["{0:04d}_{1}".format(n + 1, SITE[n]) for n in range(20)])
    assert how.count("name") == 20, how


def test_anchors_that_disagree_with_each_other_are_dropped(chapters):
    #b and d swapped on disk
    held = ["0001_a.png", "0002_d.png", "0003_c.png", "0004_b.png"]
    aligned, how, anchors, trouble = chapters.align(walked(["a.png", "b.png", "c.png", "d.png"]), held)
    assert 2 <= len(anchors) <= 3, "keeps the longest run that goes forwards: {0}".format(anchors)
    assert trouble or how.count("name") < 4, "says something is wrong rather than nothing: {0}".format(
        (anchors, trouble, how))


def test_unpadded_numbers_are_read_in_numeric_order(chapters, tmp_path):
    for name in ("1.png", "2.png", "10.png", "9.png", "100.png"):
        (tmp_path / name).write_bytes(b"x")
    assert chapters.folder_pages(str(tmp_path)) == ["1.png", "2.png", "9.png", "10.png", "100.png"]


def test_more_files_than_pages_is_reported_too(chapters):
    aligned, how, anchors, trouble = chapters.align(walked(SITE[:10]), HELD[:12])
    assert trouble and trouble[0]["files"] - trouble[0]["pages"] == 2, \
        "should say 10 walked, 12 held: {0}".format(trouble)


@pytest.fixture
def sized(tmp_path):
    held = ["0001.png", "0002.png", "0003.png"]
    for name, size in zip(held, (100, 200, 300)):
        (tmp_path / name).write_bytes(b"x" * size)
    right = [{"n": n, "url": "u", "file": "x.png", "bytes": size} for n, size in ((1, 100), (2, 200), (3, 300))]
    return str(tmp_path), held, right


def test_a_correct_alignment_agrees_with_the_sizes_the_site_reports(chapters, sized):
    folder, held, right = sized
    agree, changed, conflict = chapters.verify(folder, held, right, held)
    assert (agree, changed, len(conflict)) == (3, 0, 0), (agree, changed, conflict)


def test_a_swapped_pair_is_caught_landing_on_another_pages_file(chapters, sized):
    folder, held, right = sized
    moved = [dict(page) for page in right]
    moved[0]["bytes"], moved[1]["bytes"] = 200, 100
    agree, changed, conflict = chapters.verify(folder, held, moved, held)
    assert len(conflict) == 2, conflict


def test_re_uploaded_images_are_not_called_a_conflict(chapters, sized):
    folder, held, right = sized
    reissued = [dict(page, bytes=size) for page, size in zip(right, (111, 222, 333))]
    agree, changed, conflict = chapters.verify(folder, held, reissued, held)
    assert (agree, changed, len(conflict)) == (0, 3, 0), (agree, changed, conflict)
