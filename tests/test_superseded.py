#two spellings of one page: the key that tells them apart from two different pages, and dropping the old
#spelling once the new one is saved.
import pytest

from comiclib.guards import drop_superseded


@pytest.mark.parametrize("a, b", [
    ("0742_a-page-title.png.png", "a-page-title.png"),          # extension appended twice
    ("0323_another-page.jpg.png", "another-page.jpg.png"),      # jpg then png, unchanged today
    ("0001_a-page.png", "a-page.png"),                          # just the number prefix
    ("1484_Mixed-Case-Page.jpg.png", "Mixed-Case-Page.jpg"),    # both at once
])
def test_two_spellings_of_one_page_share_a_key(mirror, a, b):
    assert mirror.page_key(a) == mirror.page_key(b), "{0} vs {1}".format(mirror.page_key(a), mirror.page_key(b))


@pytest.mark.parametrize("a, b", [("0001_alpha.png", "0002_beta.png"), ("0001_page-one.png", "0001_page-two.png")])
def test_genuinely_different_pages_do_not_collide(mirror, a, b):
    assert mirror.page_key(a) != mirror.page_key(b)


@pytest.mark.parametrize("existing, expect_gone", [
    (["0743_a-page-title.png.png"], True),   # extension appended twice
    (["0743.png"], True),                     # renumbered by hand to digits
    (["0742_other.png"], False),              # a different page is safe
    ([], False),                              # nothing to drop
])
def test_the_new_spelling_is_kept_and_the_old_one_dropped(mirror, tmp_path, existing, expect_gone):
    keeping = "0743_a-page-title.png"
    for name in existing:
        (tmp_path / name).write_bytes(b'old')
    (tmp_path / keeping).write_bytes(b'new')
    dropped = []
    drop_superseded(str(tmp_path), 743, keeping, dropped)
    left = sorted(p.name for p in tmp_path.iterdir())
    gone = bool(existing) and existing[0] not in left
    assert gone == expect_gone and keeping in left, left
    #and what went is handed back, so the archive can drop it too
    assert dropped == (existing[:1] if expect_gone else []), dropped
