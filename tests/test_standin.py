#a page kept as something no reader can show: which files count as one, what the stand-in says, and that
#a comic's readme is not mistaken for a page
import os
import zipfile

import pytest


@pytest.fixture
def folder(tmp_path):
    def put(name, text):
        (tmp_path / name).write_text(text, encoding="utf-8")

    put('0007.txt', "https://example.com/video/abc123\n")
    put('0009.url', "https://example.com/video/12345678\n")
    put('README.txt', "This comic was saved by hand.\nSee https://example.com/about for the story.\n")
    put('notes.txt', "nothing here is an address\n")
    #a file of links that names no page of the comic, so it is not one
    put('links.txt', "https://example.com/only-an-address\n")
    #a note with the video's name run straight into its address, named like its page
    put('0021.txt', "The Comic's Big Story trailer"
                    "https://example.com/embed/_Abc-123?feature=oembed\n")
    put('0012.swf', "fake flash")
    put('0015.mp4', "not really a video")
    put('0003.png', "not really a png")
    return str(tmp_path)


@pytest.mark.parametrize("name, expected", [
    ('0007.txt', True), ('0009.url', True), ('0012.swf', True), ('0015.mp4', True),
    ('README.txt', False), ('notes.txt', False), ('0003.png', False),
    ('0021.txt', True), ('links.txt', False)])
def test_which_files_hold_a_page(chapters, folder, name, expected):
    assert bool(chapters.held_otherwise(folder, name)) == expected


def test_a_readme_is_not_swallowed_even_though_it_mentions_an_address(chapters, folder):
    assert not chapters.held_otherwise(folder, 'README.txt'), "because it is not named like a page"
    assert not chapters.held_otherwise(folder, 'links.txt'), "nor a file of links that names no page"
    address = chapters.address_in(os.path.join(folder, '0007.txt'))
    assert address[0] == "https://example.com/video/abc123", "while a note named for its page is read"


def test_what_the_folder_counts_as_pages(chapters, folder):
    held = chapters.folder_pages(folder, others=True)
    assert held == ['0003.png', '0007.txt', '0009.url', '0012.swf', '0015.mp4', '0021.txt'], \
        "the pages and the pages held otherwise, and nothing else"
    assert chapters.folder_pages(folder) == ['0003.png'], "and without asking, only the pictures"


def test_the_stand_in_is_a_png_named_for_its_page_and_packs_into_a_cbz(chapters, folder, tmp_path):
    entry, made = chapters.archive_entry(folder, '0015.mp4')
    assert entry == '0015.png', "it is named for the page it stands in for"
    assert made[:8] == b'\x89PNG\r\n\x1a\n', "it is a png"
    assert 1000 < len(made) < 400000, "of a sensible size: {0}".format(len(made))
    entry2, made2 = chapters.archive_entry(folder, '0007.txt')
    assert entry2 == '0007.png' and made2[:4] == b'\x89PNG', "a note becomes a page too"
    assert chapters.archive_entry(folder, '0015.mp4')[1] == made, \
        "drawing it twice gives the same bytes, so packing is not rewritten every time"
    entry3, made3 = chapters.archive_entry(folder, '0003.png')
    assert entry3 == '0003.png' and made3 is None, "an ordinary page is left alone"

    #both sit in a cbz without complaint
    cbz = tmp_path / "standin_check.cbz"
    with zipfile.ZipFile(str(cbz), 'w') as zf:
        zf.writestr(entry, made)
        zf.writestr(entry2, made2)
    with zipfile.ZipFile(str(cbz)) as zf:
        assert zf.testzip() is None
