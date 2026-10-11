#a chapter's banner: the picture a chapter list shows for each chapter - drawn as its heading, inside the
#heading beside its name, or a storyline's thumbnail above its header - recorded with the chapter, and never a
#page's thumbnail or the site's own logo. and the shelf a comic's chapters go on is the one they are on.
import os

from test_archive import BOXED, read_walked
from test_drawn_chapters import drawn, read


def test_a_drawn_heading_is_its_chapters_banner(chapters):
    html, pages = drawn([3, 4, 2])
    found, _, _ = read(chapters, html, pages)
    assert [c["image"] for c in found] == ["https://comic.example.com/chapter{0}.png".format(n) for n in (1, 2, 3)]


def test_a_picture_inside_a_written_heading_is_its_banner(chapters):
    html = ('<html><body><h2><img src="/banners/nine.jpg"> Chapter Nine: The Fall</h2>'
            '<a href="/p/1">1</a><a href="/p/2">2</a></body></html>')
    found, _, _ = read(chapters, html, ['https://comic.example.com/p/1', 'https://comic.example.com/p/2'])
    assert [(c["label"], c["image"]) for c in found] == \
        [("Chapter Nine: The Fall", "https://comic.example.com/banners/nine.jpg")]


def test_a_storylines_thumbnail_is_its_banner(chapters):
    walk = ["https://x.test/strip/{0}".format(n) for n in range(1, 17)]
    found = read_walked(chapters, BOXED, "https://x.test/strip/archive", walk)
    assert [c["image"] for c in found] == ["https://x.test/strip/t.jpg"] * 3


def test_a_gallery_of_page_thumbnails_and_the_sites_logo_are_no_chapters_banner(chapters):
    html = ('<html><body><h1><a href="/"><img src="logo.png"></a></h1>'
            '<h2>Chapter 1</h2><a href="/p/1"><img src="th1.png"></a><a href="/p/2"><img src="th2.png"></a>'
            '<h2>Chapter 2</h2><a href="/p/3"><img src="th3.png"></a><a href="/p/4"><img src="th4.png"></a>'
            '</body></html>')
    found, _, _ = read(chapters, html, ['https://comic.example.com/p/{0}'.format(n) for n in range(1, 5)])
    assert [(c["label"], c["image"]) for c in found] == [("Chapter 1", None), ("Chapter 2", None)]


def test_a_banner_is_kept_when_saved_and_through_a_correction_by_hand(chapters):
    walk = [{"n": n, "url": "https://comic.example.com/p/{0}".format(n), "file": "{0:04d}.png".format(n)}
            for n in range(1, 9)]
    found = [{"label": "Chapter 1", "start_page": 1, "image": "https://comic.example.com/c1.png"},
             {"label": "Chapter 2", "start_page": 5, "image": "https://comic.example.com/c2.png"}]
    fixed, _, _ = chapters.apply_fixes(found, walk, [{"page": 5, "label": "The Second Part"}])
    settled = chapters.settle_chapters(fixed, walk)
    assert [chapters.chapter_record(c).get("image") for c in settled] == \
        ["https://comic.example.com/c1.png", "https://comic.example.com/c2.png"], \
        "renamed by hand, it is still the chapter the list showed a banner for"


def test_a_comic_packs_into_the_shelf_its_chapters_are_on(chapters, tmp_path):
    #moved by hand out of a folder nested in a folder of its own name: the next pack goes where they are now,
    #not back where the archive's name would put them
    root = tmp_path / "library"
    (root / "CBZs" / "My_Comic").mkdir(parents=True)
    comic = root / "Uncompressed" / "My Comic"
    comic.mkdir(parents=True)
    metadata = {"settings": {"cbz_path": "CBZs/My_Comic/My_Comic.cbz"}, "chapters": {"folder": "CBZs/My_Comic"}}
    assert chapters.chapter_folder(str(comic), metadata, str(root)) == str(root / "CBZs" / "My_Comic")
    #and packed the first time, a shelf folder named with underscores for the comic's spaces is its own
    del metadata["chapters"]
    assert chapters.chapter_folder(str(comic), metadata, str(root)) == os.path.join(str(root), "CBZs", "My_Comic")
