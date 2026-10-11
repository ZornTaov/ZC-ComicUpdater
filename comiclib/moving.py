#moving a comic to another folder of the library - in under its author's, say - with everything that says
#where it lives moved alongside: its archive or its chapter archives on the CBZs shelf, the settings naming
#them, and the name of its index, which is made from where the comic was. moving the pages folder alone
#left the archive filed under the old place, so packing wrote every chapter a second time beside the first
#and the index went unfound. the comic keeps its own name: chapter archives, the paths inside every archive
#and the series in each ComicInfo are all made from it, so only the place it sits in changes.
import os
import re

from comiclib import metadata as sidecar
from comiclib.cbz import PAGES_TREE, SHELF, default_path, shelf
from comiclib.chapters.index import index_path
from comiclib.chapters.packing import chapter_folder
from comiclib.metadata import METADATA_FILE
from comiclib.pages import PICTURE

#the same fifty the editor keeps, since a move is shown among its edits
kept_edits = 50
#the endings a cover beside an archive is looked for under, as the reader looks for one
pictures = (".jpg", ".jpeg", ".png", ".webp", ".gif")


class Refused(Exception):
    #a move that would not leave the comic whole, said in a way that says what to do instead
    pass


def plain(text):
    #the same name however its words are joined, as the chapter shelf reads it: My_Comic is My Comic
    return re.sub(r'[\s_\-.]+', ' ', text).strip().lower()


def same(one, other):
    return os.path.normcase(os.path.abspath(one)) == os.path.normcase(os.path.abspath(other))


def within(path, folder):
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def relative(path, root):
    return os.path.relpath(path, root).replace(os.sep, '/')


def full(path, root):
    return path if os.path.isabs(path) else os.path.join(root, path.replace('/', os.sep))


def filed_like(unit, folder, new_folder):
    #where an archive, or a folder of them, goes when its comic moves - or (None, why) for one that stays.
    #one beside the pages stays beside them, and one on the CBZs shelf in the place matching the pages' goes
    #to the place matching where they go. anything else was put where it is on purpose by someone, and a
    #move has no business guessing what they meant by it
    parent, new_parent = os.path.dirname(folder), os.path.dirname(new_folder)
    if same(os.path.dirname(unit), parent):
        return os.path.join(new_parent, os.path.basename(unit)), None
    tree, found = shelf(folder)
    if (not found or not within(unit, found) or same(unit, found)
            or not same(os.path.join(tree, os.path.relpath(os.path.dirname(unit), found)), parent)):
        return None, "it is not filed in the place matching the pages'"
    new_tree, new_found = shelf(new_folder)
    if not new_found:
        return None, "the pages are leaving the {0} folder, so there is no place on the {1} shelf to match".format(
            PAGES_TREE.title(), SHELF)
    return os.path.join(new_found, os.path.relpath(new_parent, new_tree), os.path.basename(unit)), None


def own_folder(path, folder):
    #a folder is moved whole only when it is plainly this comic's: named after it, as the chapter shelf names
    #one. a folder of chapters recorded as an author's would otherwise take every other comic in it along
    name = os.path.basename(folder)
    return plain(os.path.basename(path)) in (plain(name), plain(name + "_chapters"))


#how packing names a chapter's archive, "<Comic> - c007 - <label>.cbz": a shelf folder holding its own
#name's chapters is that comic's, not a folder of comics
CHAPTER_FILE = re.compile(r"^(?P<series>.+?) - c\d+(?: - .*)?\.cbz$", re.I)


def inside_library(root, folder):
    return os.path.join(root, *[part for part in str(folder or "").replace("\\", "/").split("/") if part])


def places(root, under, max_depth=5, shelf=None):
    #every folder a comic could be moved into, as the place its pages would go: each folder below the pages
    #folder, and each on the archive shelf as the pages folder matching it. an author whose archives are filed
    #on the shelf has no pages folder until a comic of theirs is moved there, and a list made from the comics
    #alone never offered one. a comic is never gone into, nor offered; nor is a folder of loose pages - a
    #comic not adopted yet - or a comic's own folder of chapter archives; nor anything so deep that a comic put
    #in it would be past where the library is searched. one listing a folder, never one of a comic's pages
    root = os.path.abspath(root)
    pages_at = inside_library(root, under)
    found = set()

    def visit(folder, depth, place, offered):
        try:
            with os.scandir(folder) as listing:
                entries = [entry for entry in listing if not entry.name.startswith(".")]
        except OSError:
            return
        here = os.path.join(pages_at, os.path.relpath(folder, place)) if place else folder
        if not offered(folder, entries, here):
            return
        found.add(relative(here, root))
        #a comic put in a folder sits one deeper than it, and has to be within the depth searched
        if depth + 2 > max_depth:
            return
        for entry in entries:
            if entry.is_dir() and not os.path.isfile(os.path.join(entry.path, METADATA_FILE)):
                visit(entry.path, depth + 1, place, offered)

    def pages_folder(folder, entries, here):
        #pages straight inside it are a comic's, if not one tracked yet
        return not any(PICTURE.search(entry.name) and entry.is_file() for entry in entries)

    def shelf_folder(folder, entries, here):
        #a comic's own folder on the shelf - its archive, or its chapters, named as the folder is - is that
        #comic, whether or not it is tracked; as is one whose matching pages folder is a comic
        name = plain(os.path.basename(folder))

        def named_for(entry):
            chapter = CHAPTER_FILE.match(entry.name)
            stem = chapter.group("series") if chapter else os.path.splitext(entry.name)[0]
            return entry.name.lower().endswith(".cbz") and plain(stem) == name

        own = any(entry.is_file() and named_for(entry) for entry in entries)
        return not own and not os.path.isfile(os.path.join(here, METADATA_FILE))

    depth = 0 if same(pages_at, root) else len(relative(pages_at, root).split("/"))
    if os.path.isdir(pages_at) and not os.path.isfile(os.path.join(pages_at, METADATA_FILE)):
        visit(pages_at, depth, None, pages_folder)
    shelf_at = inside_library(root, shelf) if shelf else None
    if shelf_at and os.path.isdir(shelf_at) and not same(shelf_at, pages_at):
        visit(shelf_at, depth, shelf_at, shelf_folder)
    found.discard(".")
    return sorted(found, key=str.lower)


def plan(folder, root, into, max_depth=5):
    #what moving this comic into that folder of the library would do, without doing any of it. raises
    #Refused for a move that cannot be made whole, before anything is touched
    folder, root = os.path.abspath(folder), os.path.abspath(root)
    name = os.path.basename(folder)
    into = str(into or "").strip().strip('"').replace("\\", "/")
    parts = [part for part in into.split("/") if part not in ("", ".")]
    if ".." in parts or re.match(r"^[A-Za-z]:", into) or into.startswith("/"):
        raise Refused("the folder to move it into has to be inside the library, like {0}/SomeAuthor".format(
            PAGES_TREE.title()))
    new_folder = os.path.join(root, *parts, name)
    if same(new_folder, folder):
        raise Refused("it is in {0} already".format("/".join(parts) or "the top of the library"))
    if within(new_folder, folder):
        raise Refused("a comic cannot be moved into its own folder")
    if len(parts) + 1 > max_depth:
        raise Refused("the library is only searched {0} folders deep, so the comic would not be found there "
                      "again".format(max_depth))
    #nothing inside a comic is looked at as another comic, so one moved into another would vanish
    step = root
    for part in parts:
        step = os.path.join(step, part)
        if os.path.isfile(os.path.join(step, METADATA_FILE)):
            raise Refused("{0} is a comic of its own, and nothing inside a comic is found as another "
                          "one".format(relative(step, root)))

    metadata = sidecar.load(os.path.join(folder, METADATA_FILE))
    metadata = sidecar.migrate(metadata) or metadata
    settings = metadata.get("settings") or {}
    moves, stays = [], []

    def add(source, target, what):
        #a folder of chapters holding the single archive too is moved once, with the archive inside it
        if any(within(source, held) for held, _, _ in moves):
            return
        moves[:] = [move for move in moves if not within(move[0], source)]
        moves.append((source, target, what))

    #the single archive: where the settings say, or where the shelf rule puts it when they say nothing
    stored = settings.get("cbz_path")
    archive = full(stored, root) if stored else default_path(folder)
    archive_to = None
    if os.path.isfile(archive) or stored:
        target, why = filed_like(archive, folder, new_folder)
        unit = archive
        if not target and own_folder(os.path.dirname(archive), folder):
            #a single archive kept in a folder of the comic's own name on the shelf: the folder goes
            unit = os.path.dirname(archive)
            target, why = filed_like(unit, folder, new_folder)
        if target:
            archive_to = os.path.join(target, os.path.relpath(archive, unit)) if unit != archive else target
            if os.path.exists(unit):
                add(unit, target, "archive" if unit == archive else "archive folder")
            if unit == archive:
                #a cover beside the archive under its name, which is where the reader writes one it was given
                #and where other readers look: left behind, it would be the cover of nothing
                stem = os.path.splitext(archive)[0]
                for ending in pictures + tuple(ending.upper() for ending in pictures):
                    if os.path.isfile(stem + ending):
                        add(stem + ending, os.path.splitext(target)[0] + ending, "cover")
        elif os.path.isfile(archive):
            stays.append((archive, why))

    #the chapter archives, where packing recorded them or would look for them
    chapters = metadata.get("chapters") or {}
    chapters_to = None
    if chapters.get("folder") or chapters.get("list"):
        held = chapter_folder(folder, metadata, root)
        if os.path.isdir(held):
            target, why = filed_like(held, folder, new_folder)
            if target and not own_folder(held, folder):
                target, why = None, "it is not named after the comic, so it may hold more than this comic"
            if target:
                chapters_to = target
                add(held, target, "chapter archives")
            else:
                stays.append((held, why))

    #the pages last, so a move that fails part way has left the comic itself where it was
    moves.append((folder, new_folder, "pages"))
    for _, target, _ in moves:
        if os.path.exists(target):
            raise Refused("{0} is already there; move or rename that first".format(relative(target, root)))

    #the index keeps its name and its place in the config folder. its name is made from where the comic
    #was, so the comic is made to say it, which is the second place every reader of the index looks
    index = index_path(folder, root)
    return {"folder": folder, "root": root, "name": relative(folder, root), "to": relative(new_folder, root),
            "new_folder": new_folder, "moves": moves, "stays": stays, "metadata": metadata,
            "archive": archive, "archive_to": archive_to, "chapters_to": chapters_to,
            "index": index if os.path.isfile(index) else None}


def describe(planned):
    #a line for each thing the move does, and whether it is something left behind, which wants noticing
    root = planned["root"]
    lines = [("{0}: {1} -> {2}".format(what, relative(source, root), relative(target, root)), False)
             for source, target, what in planned["moves"]]
    lines += [("{0} stays where it is: {1}".format(relative(path, root), why), True)
              for path, why in planned["stays"]]
    if planned["index"]:
        lines.append(("index: {0} stays in the config folder, named in the comic so it is still found".format(
            os.path.basename(planned["index"])), False))
    return lines


def placed(path, moves):
    #where a path ends up once the moves are made
    for source, target, _ in moves:
        if within(path, source):
            rest = os.path.relpath(path, source)
            return target if rest == "." else os.path.join(target, rest)
    return path


def make_folders(folder):
    #the folders that had to be made, outermost first, so a move undone can take them away again
    made = []
    while not os.path.isdir(folder):
        made.insert(0, folder)
        folder = os.path.dirname(folder)
    for each in made:
        os.mkdir(each)
    return made


def tidy(folder, root):
    #the folders a move left empty - an author's with nothing else in it - up to the shelf or the library.
    #rmdir removes nothing that holds anything, so a folder holding as much as a stray thumbnail stays
    while within(folder, root) and not same(folder, root) and \
            os.path.basename(folder).lower() not in (PAGES_TREE, SHELF.lower()):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


def carry_out(planned):
    #renames, never copies: within one library each is a moment however many pages it holds, and a copy cut
    #off part way would leave a comic in two halves. one that fails puts back every one made before it
    root, moves = planned["root"], planned["moves"]
    done, made = [], []
    try:
        for source, target, _ in moves:
            made += make_folders(os.path.dirname(target))
            os.rename(source, target)
            done.append((source, target))
        sidecar.write(planned["new_folder"], moved_metadata(planned))
    except OSError as error:
        stuck = []
        for source, target in reversed(done):
            try:
                os.rename(target, source)
            except OSError:
                stuck.append("{0} is at {1}".format(relative(source, root), relative(target, root)))
        for each in reversed(made):
            try:
                os.rmdir(each)
            except OSError:
                pass
        if stuck:
            raise Refused("the move failed ({0}) and could not all be put back: {1}. Move those back by hand "
                          "before the next update".format(error, "; ".join(stuck)))
        raise Refused("the move failed and everything was put back where it was: {0}. If something has the "
                      "comic open - a reader, a file browser - close it and try again".format(error))
    for source, _ in done:
        tidy(os.path.dirname(source), root)
    return [line for line, _ in describe(planned)]


def moved_metadata(planned):
    #the metadata as it reads in its new place: every path in it that the move changed, and the move itself
    #among the edits, so the editor shows where the comic came from
    root, moves = planned["root"], planned["moves"]
    metadata = planned["metadata"]
    settings = dict(metadata.get("settings") or {})
    changed = {"folder": [planned["name"], planned["to"]]}
    if settings.get("output"):
        settings["output"] = planned["to"]
    stored = settings.get("cbz_path")
    archive = planned["archive_to"] or planned["archive"]
    if stored:
        shown = archive if os.path.isabs(stored) else relative(archive, root)
        if shown != stored:
            settings["cbz_path"] = shown
    elif os.path.isfile(archive) and not same(default_path(planned["new_folder"]), archive):
        #an archive the shelf rule found, which the rule would not find from the new place: named outright
        settings["cbz_path"] = relative(archive, root)
    if settings.get("cbz_path") != stored:
        changed["cbz_path"] = [stored, settings.get("cbz_path")]
    metadata["settings"] = settings

    chapters = metadata.get("chapters") or {}
    recorded = chapters.get("folder")
    if recorded and planned["chapters_to"]:
        now = placed(full(recorded, root), moves)
        shown = now if os.path.isabs(recorded) else relative(now, root)
        if shown != recorded:
            chapters["folder"] = shown
            changed["chapters_folder"] = [recorded, shown]

    history = metadata.setdefault("history", {})
    if planned["index"] and history.get("index_cache") != os.path.basename(planned["index"]):
        history["index_cache"] = os.path.basename(planned["index"])
    stamp = sidecar.now_stamp()
    metadata["updated"] = stamp
    history["edits"] = (history.get("edits") or [])[-(kept_edits - 1):] + [{"at": stamp, "changed": changed}]
    #every rename, as the reader reads it with metadata.before_moves: it keeps a comic's place and cover by
    #where the comic is, and this is how it finds them again under the new place
    moved = [{"what": what, "from": relative(source, root), "to": relative(target, root)}
             for source, target, what in moves]
    history["moves"] = (history.get("moves") or [])[-(kept_edits - 1):] + [{"at": stamp, "moved": moved}]
    return metadata
