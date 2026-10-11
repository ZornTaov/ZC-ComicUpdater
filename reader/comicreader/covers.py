#a cover for a comic, a folder, a series or an author. what wins: one chosen in the reader - a page of a comic,
#or a picture put in - then a picture already on the shelf where other readers look for one (an archive's
#own name with a picture's ending beside it, a folder's cover.jpg), then the comic's first page.
#
#a cover chosen in the reader is kept in its data folder, and written onto the shelf as well where there is a
#place for it, so other readers show it too: beside a comic's archive, or in a folder of the shelf. never in a
#comic's own folder of pages, which the scraper would pack as a page
import hashlib
import io
import os

from comiclib.metadata import METADATA_FILE

#what a target is a cover of: "comic:<id>", "folder:<place>", "series:<name>", "author:<name>"
KINDS = ("comic", "folder", "series", "author")
#the names a folder's own picture goes by, in the order they are looked for, as other readers look for them
FOLDER_NAMES = ("cover", "folder", "poster")
ENDINGS = (".jpg", ".jpeg", ".png", ".webp")
#the size a cover written onto the shelf is kept to: plenty for any reader's shelf, and no page-sized file
SHELF_SIZE = (1200, 1800)
#what an upload can be at most
MOST = 20 << 20


class Unusable(Exception):
    #why a cover could not be set, said as what to do about it
    pass


def picture(body, size, quality=85):
    #a picture as a jpeg no bigger than size. Pillow, since it has to be scaled well and this is the
    #reader's own image, not the scraper's
    from PIL import Image
    with Image.open(io.BytesIO(body)) as found:
        found = found.convert("RGB")
        found.thumbnail(size)
        out = io.BytesIO()
        found.save(out, "JPEG", quality=quality)
    return out.getvalue()


def split(target):
    kind, _, key = target.partition(":")
    if kind not in KINDS or not key:
        raise Unusable("a cover is for comic:<id>, folder:<path>, series:<name> or author:<name>, not {0!r}".format(target))
    return kind, key


def stamped(path):
    found = os.stat(path)
    return "{0:x}{1:x}".format(found.st_size, found.st_mtime_ns)[-12:]


def comic_shelf_picture(library, comic):
    #a picture beside a comic's one archive, named as the archive is: how other readers keep a book's cover
    if comic["kind"] != "archive" or len(comic["sources"]) != 1:
        return None
    path = comic["sources"][0]
    there = library.pictures.get(os.path.normpath(os.path.dirname(path))) or {}
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    return next((there[stem + ending] for ending in ENDINGS if stem + ending in there), None)


def folder_of(library, place):
    return os.path.normpath(os.path.join(library.config.library, place.replace("/", os.sep)))


def folder_shelf_picture(library, place):
    there = library.pictures.get(folder_of(library, place)) or {}
    return next((there[name + ending] for name in FOLDER_NAMES for ending in ENDINGS if name + ending in there), None)


def chosen_page(library, row):
    #the comic and page a chosen cover is, found again by the page itself, or where it was if it has gone
    comic = library.comics.get(row.get("comic"))
    if comic is None:
        return None
    pages = library.stream(comic)["pages"]
    if not pages:
        return None
    at = next((n for n, page in enumerate(pages) if page["key"] == row.get("key")), None)
    if at is None:
        at = max(0, min(int(row.get("position") or 0), len(pages) - 1))
    return comic, at, pages[at]


def resolve(library, target, comic=None, stream=None):
    #(token, where) for a target's cover: where is ("file", path) or ("page", comic, n). None for a folder,
    #series or author with nothing of its own, which is shown with its first comic's cover
    row = library.chosen.get(target)
    if row and row.get("file"):
        path = os.path.join(library.config.data, "covers", row["file"])
        if os.path.isfile(path):
            return "u" + stamped(path), ("file", path)
    if row and row.get("comic"):
        found = chosen_page(library, row)
        if found:
            return "p" + found[2]["v"], ("page", found[0], found[1])
    kind, key = target.partition(":")[::2]
    on_shelf = comic_shelf_picture(library, comic) if kind == "comic" and comic else \
        folder_shelf_picture(library, key) if kind == "folder" else None
    if on_shelf and os.path.isfile(on_shelf):
        return "s" + stamped(on_shelf), ("file", on_shelf)
    if comic is not None:
        pages = (stream or library.stream(comic))["pages"]
        if pages:
            return pages[0]["v"], ("page", comic, 0)
    return None


def token(library, target, comic=None, stream=None):
    found = resolve(library, target, comic, stream)
    return found[0] if found else None


def group_covers(library):
    #the covers of folders, series and authors that have one of their own, chosen or on the shelf, for the
    #library's tiles to show in place of their first comic's
    out = {}
    for target in library.chosen:
        if not target.startswith("comic:"):
            found = token(library, target)
            if found:
                out[target] = {"v": found, "chosen": True}
    root = os.path.normpath(library.config.library)
    for folder in library.pictures:
        if folder == root:
            continue
        target = "folder:" + os.path.relpath(folder, root).replace(os.sep, "/")
        if target not in out:
            found = token(library, target)
            if found:
                out[target] = {"v": found, "chosen": False}
    return out


def body_of(library, where):
    #the picture's own bytes
    if where[0] == "file":
        with open(where[1], "rb") as f:
            return f.read()
    comic, at = where[1], where[2]
    page = library.stream(comic)["pages"][at]
    source = library.sources.cached(comic["sources"][page["source"]]) or library.sources.get(
        comic["sources"][page["source"]], "folder" if comic["kind"] == "folder" else "archive")
    return library.sources.page(source, page)[0]


def shelf_place(library, target):
    #where on the shelf a target's cover is written for other readers, or None where there is nowhere: beside
    #a comic's one archive, or in a folder of the shelf that is no comic's own folder of pages
    kind, key = split(target)
    if kind == "comic":
        comic = library.comics.get(key)
        if comic is None or comic["kind"] != "archive" or len(comic["sources"]) != 1:
            return None
        return os.path.splitext(comic["sources"][0])[0] + ".jpg"
    if kind == "folder":
        folder = folder_of(library, key)
        root = os.path.normpath(library.config.library)
        if folder == root or not folder.startswith(root + os.sep) or not os.path.isdir(folder) or \
                os.path.isfile(os.path.join(folder, METADATA_FILE)):
            return None
        return os.path.join(folder, "cover.jpg")
    return None


def write_to_shelf(library, target, body):
    #the cover written onto the shelf, aside and moved into place. answers where, and what it was left as,
    #or why it could not be: the cover is still the reader's either way
    path = shelf_place(library, target)
    if path is None:
        return None, None
    try:
        made = picture(body, SHELF_SIZE)
        with open(path + ".writing", "wb") as f:
            f.write(made)
        os.replace(path + ".writing", path)
    except OSError as error:
        try:
            os.remove(path + ".writing")
        except OSError:
            pass
        return None, "kept in the reader only: it could not be written beside the comic ({0})".format(error.strerror or error)
    library.pictures.setdefault(os.path.normpath(os.path.dirname(path)), {})[os.path.basename(path).lower()] = path
    found = os.stat(path)
    return [path, found.st_size, found.st_mtime_ns], None


def check_target(library, target):
    kind, key = split(target)
    if kind == "comic" and key not in library.comics:
        raise Unusable("there is no comic {0}; the library may have changed since the page was drawn".format(key))
    return kind, key


def choose_page(library, target, comic_id, n):
    check_target(library, target)
    comic = library.comics.get(comic_id)
    if comic is None:
        raise Unusable("there is no comic {0}".format(comic_id))
    pages = library.stream(comic)["pages"]
    if not 0 <= n < len(pages):
        raise Unusable("{0} has {1} pages".format(comic["title"], len(pages)))
    row = {"comic": comic_id, "key": pages[n]["key"], "position": n}
    return keep(library, target, row, body_of(library, ("page", comic, n)))


def choose_upload(library, target, body):
    check_target(library, target)
    if not body:
        raise Unusable("no picture came with the upload")
    if len(body) > MOST:
        raise Unusable("that picture is over {0} MB; a cover needs far less".format(MOST >> 20))
    try:
        kept = picture(body, SHELF_SIZE, 90)
    except Exception:  # noqa: BLE001 - whatever Pillow cannot open is not a picture
        raise Unusable("that file is not a picture the reader can open")
    name = "custom/{0}.jpg".format(hashlib.sha1(target.encode("utf-8")).hexdigest()[:16])
    path = os.path.join(library.config.data, "covers", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".writing", "wb") as f:
        f.write(kept)
    os.replace(path + ".writing", path)
    return keep(library, target, {"file": name}, kept)


def keep(library, target, row, body):
    old = library.chosen.get(target) or {}
    wrote, note = write_to_shelf(library, target, body)
    if wrote:
        row["wrote"] = wrote
    elif old.get("wrote"):
        #a picture this reader put on the shelf before, still as it was left: still its own to replace later
        row["wrote"] = old["wrote"]
    library.store.save_cover(target, row)
    library.chosen[target] = row
    return {"target": target, "v": token(library, target, library.comics.get(target[6:]) if target.startswith("comic:") else None),
            "shelf": os.path.relpath(wrote[0], library.config.library).replace(os.sep, "/") if wrote else None,
            "note": note}


def forget(library, target):
    #back to what the cover would be without a choice. a picture this reader put on the shelf goes too, if it
    #is still just as it was left; one changed since is someone else's now, and stays
    split(target)
    row = library.chosen.pop(target, None) or {}
    library.store.forget_cover(target)
    note = None
    if row.get("file"):
        try:
            os.remove(os.path.join(library.config.data, "covers", row["file"]))
        except OSError:
            pass
    wrote = row.get("wrote")
    if wrote:
        path = wrote[0]
        try:
            found = os.stat(path)
            if [found.st_size, found.st_mtime_ns] == wrote[1:]:
                os.remove(path)
                there = library.pictures.get(os.path.normpath(os.path.dirname(path))) or {}
                there.pop(os.path.basename(path).lower(), None)
            else:
                note = "{0} was changed since the reader wrote it, so it was left on the shelf".format(
                    os.path.basename(path))
        except OSError as error:
            note = "{0} could not be taken off the shelf ({1})".format(os.path.basename(path), error.strerror or error)
    comic = library.comics.get(target[6:]) if target.startswith("comic:") else None
    return {"target": target, "v": token(library, target, comic), "note": note}
