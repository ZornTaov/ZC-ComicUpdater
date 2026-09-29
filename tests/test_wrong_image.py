#a file that sits where a page belongs but is not the image the walk saw there: the lining up notices, says
#which page and what the site serves for it, and says how to put it right - but only for a comic whose
#files are named after their images in the first place.
import os
import time

from conftest import run, write_index, write_meta


def build(library, chapters, names, srcs):
    folder = library / "Uncompressed" / "Toy"
    folder.mkdir()
    for at, name in enumerate(names):
        path = folder / name
        path.write_bytes(bytes([at]) * (100 + at))
        #written in reading order, for --by-time to line up by
        stamp = time.time() - (len(names) - at) * 10
        os.utime(str(path), (stamp, stamp))
    write_meta(folder, {"settings": {"url": "https://x.test/1"}, "history": {}})
    write_index(chapters.index_path(str(folder), str(library), None),
                [{"n": at + 1, "url": "https://x.test/{0}".format(at + 1), "src": src,
                  "image": src.rsplit("/", 1)[-1], "bytes": 100 + at} for at, src in enumerate(srcs)])
    return folder


def align(folder, library):
    done = run("chapters.py", "align", folder, "--root", library, "--by-time")
    return done.stdout + done.stderr


def test_one_page_holding_the_wrong_image_is_named_with_the_fix(library, chapters):
    names = ["icon.png", "p2.jpg.png", "p3.jpg.png", "p4.jpg.png", "p5.jpg.png"]
    srcs = ["https://x.test/i/p{0}.jpg".format(n) for n in range(1, 6)]
    out = align(build(library, chapters, names, srcs), library)
    assert "1 file(s) here are not the image the walk saw" in out, \
        [l for l in out.splitlines() if "not the image" in l]
    #it names the page and what the site serves for it
    assert "page 1" in out and "p1.jpg" in out, [l for l in out.splitlines() if "page 1" in l]
    #and says how to put it right
    assert "--as-named" in out, out.splitlines()[-4:]


def test_a_site_that_renamed_every_image_is_not_called_wrong(library, chapters):
    #nothing here is named after its image, so there is nothing to compare, and nothing to say
    names = ["OLD_{0:04d}.png".format(n) for n in range(1, 6)]
    srcs = ["https://x.test/wp/2019/newname-{0}.jpg".format(n) for n in range(1, 6)]
    out = align(build(library, chapters, names, srcs), library)
    assert "not the image the walk saw" not in out, [l for l in out.splitlines() if "image" in l]
