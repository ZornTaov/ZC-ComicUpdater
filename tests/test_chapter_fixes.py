#corrections to where chapters begin, for the page the rule cannot place: moving a boundary, dropping
#one, and a correction that names a page the comic does not have.
import pytest

#a comic of issues, each opening on a cover, where one cover was given a name that says nothing of issues
ODD = "https://x.test/comic/2-an-odd-name/"
FIX = [{"url": ODD, "label": "Issue 2"}]


def comic():
    where = []
    for issue, held in ((1, 6), (2, 6), (3, 5)):
        where.append(ODD if issue == 2 else "https://x.test/comic/issue-{0}-cover/".format(issue))
        where += ["https://x.test/comic/issue-{0}-page-{1}/".format(issue, p) for p in range(1, held)]
    return [{"n": at + 1, "url": url, "file": "{0:04d}.png".format(at + 1)} for at, url in enumerate(where)]


@pytest.fixture
def pages():
    return comic()


@pytest.fixture
def derived(chapters, pages):
    return chapters.chapters_from_urls(pages)


def starts(found):
    return [c["start_page"] for c in found]


def test_the_rule_alone_puts_the_odd_cover_in_the_chapter_before_it(chapters, pages, derived):
    found = chapters.settle_chapters([dict(c) for c in derived], pages)
    assert starts(found) == [1, 8, 13], [(c["label"], c["start_page"]) for c in found]


def test_a_correction_moves_a_boundary(chapters, pages, derived):
    fixed, took, missed = chapters.apply_fixes([dict(c) for c in derived], pages, FIX)
    now = chapters.settle_chapters(fixed, pages)
    assert starts(now) == [1, 7, 13], "the odd cover starts its own issue: {0}".format(
        [(c["label"], c["start_page"]) for c in now])
    assert [c["label"] for c in now].count("Issue 2") == 1, "still one Issue 2, not two"
    assert now[1].get("by_hand") is True, "the moved one is marked as done by hand"
    assert (len(took), missed) == (1, []), (took, missed)


def test_a_correction_survives_the_chapters_being_worked_out_again(chapters, pages):
    again, _, _ = chapters.apply_fixes(chapters.chapters_from_urls(pages), pages, FIX)
    assert starts(chapters.settle_chapters(again, pages)) == [1, 7, 13]


def test_a_correction_applied_twice_does_not_double_it(chapters, pages, derived):
    fixed, _, _ = chapters.apply_fixes([dict(c) for c in derived], pages, FIX)
    now = chapters.settle_chapters(fixed, pages)
    twice, _, _ = chapters.apply_fixes([dict(c) for c in now], pages, FIX)
    assert starts(chapters.settle_chapters(twice, pages)) == [1, 7, 13]


def test_a_boundary_said_not_to_be_one_is_dropped(chapters, pages, derived):
    dropped, _, _ = chapters.apply_fixes([dict(c) for c in derived], pages,
                                         [{"url": "https://x.test/comic/issue-3-cover/", "drop": True}])
    after = chapters.settle_chapters(dropped, pages)
    assert len(after) == 2 and after[-1]["end_page"] == len(pages), \
        "that chapter is gone and its pages join the one before: {0}".format(
            [(c["label"], c["start_page"], c["end_page"]) for c in after])
    assert sum(c["pages"] for c in after) == len(pages) - after[0]["start_page"] + 1, \
        "every page still lands somewhere"


def test_a_correction_about_a_page_this_comic_does_not_have_is_reported(chapters, pages, derived):
    _, took, missed = chapters.apply_fixes([dict(c) for c in derived], pages, [{"url": "https://x.test/comic/nope/"}])
    assert (took, missed) == ([], ["https://x.test/comic/nope/"])


def test_a_page_named_by_address_resolves_to_its_number(chapters, pages):
    assert chapters.page_at(pages, ODD) == 7
    assert chapters.page_at(pages, "http://x.test/comic/2-an-odd-name") == 7, \
        "an address written another way still matches"
