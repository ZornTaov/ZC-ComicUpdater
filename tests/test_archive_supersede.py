#a page saved long ago under an older spelling of its name, and in the archive under it. a run that saves
#the page again under the name the site uses now has to take the old one out of the archive as well as the
#folder, or the comic shows that page twice for good.
import os
import zipfile

import pytest

from conftest import PNG, Site, run

pytestmark = [pytest.mark.browser, pytest.mark.slow]


class OnePage(Site):
    #a comic that is one page, whose image the site now calls b.png
    def do_GET(self):
        if self.path.startswith("/img/"):
            self.send(PNG, "image/png")
        else:
            self.send('<html><body><div id="wrap"><img id="comic-image" src="/img/b.png"></div></body></html>')


def test_a_page_resaved_under_a_new_name_leaves_the_archive_under_its_old_one(library, serve):
    url = serve(OnePage) + "/only"
    folder = library / "Uncompressed" / "Comic"
    folder.mkdir()
    cbz = library / "CBZs" / "Comic.cbz"

    #the library as it stands: page 2 saved years ago under the older spelling, and in the archive
    old_name = "0002_b.png.png"
    (folder / old_name).write_bytes(b"older spelling")
    (folder / "0001_a.png.png").write_bytes(b"page one")
    with zipfile.ZipFile(cbz, "w", zipfile.ZIP_STORED) as zf:
        zf.write(folder / "0001_a.png.png", "0001_a.png.png")
        zf.write(folder / old_name, old_name)

    done = run("mirror_base.py", "-p", "-i", "2", "-o", os.path.join("Uncompressed", "Comic"),
               "--cbz-path", os.path.join("CBZs", "Comic.cbz"), url, cwd=library, timeout=240)

    with zipfile.ZipFile(cbz) as zf:
        names = sorted(n for n in zf.namelist() if not n.endswith(".json"))
        readable = zf.testzip() is None
    pages = sorted(f for f in os.listdir(folder) if f != "mirror_metadata.json")
    assert done.returncode == 0, "{0}: {1}".format(done.returncode, done.stdout.strip()[-200:])
    assert len([p for p in pages if p.startswith("0002")]) == 1, "folder holds page 2 more than once: {0}".format(pages)
    assert len([n for n in names if "0002" in n]) == 1, "archive holds page 2 more than once: {0}".format(names)
    assert old_name not in names, "archive kept the old spelling: {0}".format(names)
    assert "0002_b.png" in names, "archive lost the new spelling: {0}".format(names)
    assert "0001_a.png.png" in names, "archive lost page 1: {0}".format(names)
    assert readable, "the archive no longer reads"
