#an archive built elsewhere, the way `zip -r -0 X.zip ./X` builds it: a directory entry, every path under the
#folder's name, everything stored. new pages have to go in under the same prefix, or a reader shows the comic
#as two separate groups - and appending must leave every byte already there where it is, so a sync carries
#only the new pages.
import argparse
import os
import zipfile

from conftest import write_meta

NAME = "MyComic"


def test_new_pages_are_appended_under_the_prefix_the_archive_already_uses(library, mirror, monkeypatch):
    folder = library / "Uncompressed" / NAME
    folder.mkdir()
    cbz = library / "CBZs" / (NAME + ".cbz")
    for n in range(1, 6):
        (folder / "{0:04d}_page.png".format(n)).write_bytes(b"IMAGE" + bytes([n]) * 900)
    write_meta(folder, {"schema": 2, "settings": {}})

    with zipfile.ZipFile(cbz, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(NAME + "/", b"")
        for name in sorted(os.listdir(folder)):
            zf.write(folder / name, NAME + "/" + name)
    before_size = os.path.getsize(cbz)
    before_bytes = cbz.read_bytes()

    #a new page arrives, as a real run would leave behind
    (folder / "0006_page.png").write_bytes(b"IMAGE" + b"\x06" * 900)

    args = argparse.Namespace(output=os.path.join("Uncompressed", NAME),
                              cbz_path=os.path.join("CBZs", NAME + ".cbz"))
    monkeypatch.chdir(library)
    built, added = mirror.cbz_update(args)

    with zipfile.ZipFile(built) as zf:
        names = zf.namelist()
    after_bytes = open(built, "rb").read()
    kept = 0
    for a, b in zip(before_bytes, after_bytes):
        if a != b:
            break
        kept += 1

    assert added == 1, "expected exactly the one new page appended, got {0}".format(added)
    assert len(names) == 8, "the five it already had were added again: {0}".format(names)
    assert not [n for n in names if not n.startswith(NAME + "/")], names
    assert len([n for n in names if n.endswith("mirror_metadata.json")]) == 1, names
    assert NAME + "/0006_page.png" in names, names
    #only the directory at the end, and the metadata written last, should have moved
    assert kept >= before_size - 2000, "earlier bytes rewritten: {0} of {1} kept".format(kept, before_size)

    #and running again with nothing new must leave the file completely alone
    size_after = os.path.getsize(built)
    again, again_added = mirror.cbz_update(args)
    assert again_added == 0, again_added
    assert os.path.getsize(again) == size_after
