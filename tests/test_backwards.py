#a next link that runs backwards through pages already held, told apart from a comic that merely reuses
#image names; and the guard that stops a reused name writing over a page already saved.
import pytest

#three chapters of four pages, where the site numbers each chapter's pages from one: it serves 1@2x.png,
#2@2x.png ... over and over
PER_CHAPTER = ["{0}@2x.png".format(n) for _ in range(3) for n in range(1, 5)]
#a comic of twenty pages, already held
HELD = {"p{0}.png".format(n): n for n in range(1, 21)}
#walked from page 12 downwards
BACK = ["p{0}.png".format(n) for n in range(12, 0, -1)]


def walk(mb, names, held, prefix=True, check_direction=True):
    #the decision img_save makes, page by page, without the browser or the disk: `names` are the image
    #names the site serves in order, `held` is what the folder already knows (key -> page number)
    mb.scrape_state["last_known_number"] = None
    mb.scrape_state["backwards_run"] = 0
    pages = dict(held)
    for at, name in enumerate(names, 1):
        saved = "{0:04d}_{1}".format(at, name) if prefix else name
        sits_at = pages.get(mb.page_key(saved))
        came_from = mb.scrape_state["last_known_number"]
        if mb.reads_backwards(sits_at, came_from) and check_direction:
            return at
        if sits_at is None:
            sits_at = mb.page_number(saved)
        mb.scrape_state["last_known_number"] = sits_at
        pages.setdefault(mb.page_key(saved), sits_at)
    return None


def test_a_comic_that_numbers_each_chapters_pages_from_one_walks_through(mirror):
    assert walk(mirror, PER_CHAPTER, {}) is None
    assert walk(mirror, PER_CHAPTER, {"{0}@2x.png".format(n): n for n in range(1, 5)}) is None, \
        "even when the first chapter is already held"


def test_a_next_link_that_really_runs_backwards_is_caught_early(mirror):
    stopped = walk(mirror, BACK, HELD)
    assert stopped is not None, "it is caught"
    assert stopped == 3, "and caught early, after one extra page"


def test_a_resume_walking_forward_over_held_pages_is_not_backwards(mirror):
    assert walk(mirror, ["p{0}.png".format(n) for n in range(8, 21)], HELD) is None


def test_turning_the_direction_check_off_stops_nothing(mirror):
    assert walk(mirror, BACK, HELD, check_direction=False) is None


@pytest.fixture
def would_overwrite(mirror, tmp_path):
    counter = [0]

    def check(names, prefix, bytes_for=None):
        #the real guard, against a real folder. `bytes_for` says what the site serves for each name; by
        #default every page is its own image, so a repeated name means a different page.
        bytes_for = bytes_for or (lambda at, name: b"page-" + str(at).encode())
        counter[0] += 1
        here = tmp_path / "folder{0}".format(counter[0])
        here.mkdir()
        for at, name in enumerate(names, 1):
            target = str(here / ("{0:04d}_{1}".format(at, name) if prefix else name))
            fresh = bytes_for(at, name)
            if mirror.would_lose_a_page(target, prefix, at - 1, fresh):
                return at
            with open(target, 'wb') as f:
                f.write(fresh)
        return None

    return check


def test_a_reused_name_with_no_prefix_is_caught_rather_than_written_over(would_overwrite):
    assert would_overwrite(PER_CHAPTER, prefix=False) == 5
    assert would_overwrite(PER_CHAPTER, prefix=True) is None, "with prefix on it is fine"
    assert would_overwrite(["p{0}.png".format(n) for n in range(1, 9)], prefix=False) is None, \
        "a comic with names of its own is fine either way"


def test_reaching_a_page_already_held_with_the_same_image_is_not_a_collision(would_overwrite):
    #a gap filled by hand, then a run that walks up to a page already saved by an earlier run. the same
    #page, the same image - writing it over itself loses nothing, and stopping there stops for nothing.
    same = ["p{0}.png".format(n) for n in range(1, 6)] + ["p5.png"]

    def by_name(at, name):
        return b"the image called " + name.encode()

    assert would_overwrite(same, prefix=False, bytes_for=by_name) is None
    assert would_overwrite(same, prefix=False) == 6, "but a different image under that name still is"
    assert would_overwrite(PER_CHAPTER, prefix=False) == 5, \
        "and the chapter-per-name site is still caught, since its images differ"
