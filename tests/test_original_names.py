#renumber --original: a comic another tool saved under names of its own - 0.png, 1.png, jpgs every one -
#given back the names the site gives its images, which are what find a page again in a search. numbered
#in front as well only when those names would not read in the comic's order, or two pages share one.
import json
import os

from conftest import read_meta, run, write_meta

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def lined_up(chapters, library, sources, made=None):
    #pages 1..n held as 0.png..(n-1).png, the way another tool counted them, lined up against a walk that
    #says what the site called each image. `made` is a page the site shows no image on, kept by hand
    folder = library / "Uncompressed" / "Other"
    folder.mkdir(parents=True)
    pages = []
    for n, src in enumerate(sources, 1):
        (folder / "{0}.png".format(n - 1)).write_bytes(JPEG + bytes([n]))
        page = {"n": n, "url": "https://x.test/p{0}".format(n), "file": "{0}.png".format(n - 1), "how": "size"}
        if src and n != made:
            page["src"] = "https://x.test/img/" + src
        pages.append(page)
    history = {"hand_made": [{"page": made, "file": "{0}.png".format(made - 1)}]} if made else {}
    write_meta(folder, {"schema": 2, "settings": {"url": "https://x.test/p{0}".format(len(sources)),
                                                  "prefix": False, "increment": len(sources) - 1},
                        "history": history})
    cache = chapters.index_path(str(folder), str(library), None)
    with open(cache.replace(".jsonl", ".align.json"), "w", encoding="utf-8") as f:
        json.dump({"comic": str(folder), "settled": True, "pages": pages}, f)
    return folder


def renumber(library, folder, *extra):
    return run("chapters.py", "renumber", folder, "--root", library, "--original", *extra)


def test_names_that_read_in_order_are_given_back_as_they_are(chapters, library):
    dated = ["20040222_ab.jpg", "20040223_cd.jpg", "20040225_ef.jpg", "20040301_gh.jpg"]
    folder = lined_up(chapters, library, dated)
    done = renumber(library, folder)
    assert done.returncode == 0, done.stdout[-500:]
    assert sorted(name for name in os.listdir(str(folder)) if name.endswith(".jpg")) == dated, \
        "each page under the site's own name, with no number in front"
    settings = read_meta(folder)["settings"]
    assert settings["prefix"] is False and settings["increment"] == 3, "nothing about numbering changes"


def test_names_out_of_order_are_numbered_and_new_pages_carry_on_from_the_last(chapters, library):
    #a site that changed how it names its images part way through, so the names sort wrongly
    mixed = ["2005-05-20-a.jpg", "1385274624-2005-05-23-b.png", "2005-05-25-c.jpg", "1385274700-2005-05-27-d.png"]
    folder = lined_up(chapters, library, mixed)
    done = renumber(library, folder)
    assert done.returncode == 0, done.stdout[-500:]
    assert "would not read in order" in done.stdout, done.stdout[-500:]
    #the extension is the file's own: these are jpgs, whatever the site or the other tool called them
    assert sorted(os.listdir(str(folder))) == ["0001_2005-05-20-a.jpg", "0002_1385274624-2005-05-23-b.jpg",
                                               "0003_2005-05-25-c.jpg", "0004_1385274700-2005-05-27-d.jpg",
                                               "mirror_metadata.json"]
    settings = read_meta(folder)["settings"]
    assert settings["prefix"] is True
    assert settings["increment"] == 4, "it resumes on page 4, which a run saves again under 0004_"


def test_a_name_used_twice_and_a_page_made_by_hand_are_numbered(chapters, library):
    folder = lined_up(chapters, library, ["a1.jpg", "a2.jpg", "a1.jpg", None, "a5.jpg"], made=4)
    done = renumber(library, folder)
    assert done.returncode == 0, done.stdout[-500:]
    names = sorted(os.listdir(str(folder)))
    assert names == ["0001_a1.jpg", "0002_a2.jpg", "0003_a1.jpg", "0004.jpg", "0005_a5.jpg",
                     "mirror_metadata.json"], names
    assert read_meta(folder)["history"]["hand_made"][0]["file"] == "0004.jpg", \
        "the page set by hand is still known by its file"
