#taking in what a plugin's program wrote: its pages, or its chapters as folders of pages or as archives,
#made pages of the comic numbered on from its last, with each chapter added to the comic's list and any
#ComicInfo the program wrote kept with the comic or the chapter it came with.
import os
import re
import shutil
import zipfile
import zlib

from comiclib import comicinfo
from comiclib.chapters.chapterlist import chapters_block, settle_chapters
from comiclib.chapters.index import numbered_pages
from comiclib.metadata import METADATA_FILE
from comiclib.pages import PAGE_TYPES, held_pages, page_key, page_number, safe_name, sort_key, write_page

#where a plugin's program is run, inside the comic's own folder so taking a page in is a rename. a dot
#folder, which the library's search never goes into and no archive takes in
STAGING = ".plugin-staging"
ARCHIVES = re.compile(r'\.(cbz|zip)$', re.I)
HALF_WRITTEN = "may be only part written: the program was stopped while it was writing it"


class Taken:
    #what one taking-in did: the pages added, in reading order, the chapters they started, and what was
    #left out and why
    def __init__(self):
        self.pages = []
        self.chapters = []
        self.comicinfo = None
        self.skipped = []
        self.dropped = []
        #pages the comic already had, the same file fetched again
        self.held = 0

    def view(self):
        #what a plugin's remember() is handed
        return {"pages": list(self.pages), "chapters": [chapter["label"] for chapter in self.chapters],
                "skipped": list(self.skipped)}


def staging_folder(folder):
    return os.path.join(folder, STAGING)


def files_under(staging):
    #everything the program wrote, as paths within staging with / between folders, in reading order
    found = []
    for current, dirs, files in os.walk(staging):
        for name in files:
            found.append(os.path.relpath(os.path.join(current, name), staging).replace(os.sep, '/'))
    return sorted(found, key=sort_key)


def is_comicinfo(path):
    return os.path.basename(path).lower() == comicinfo.NAME.lower()


def next_number(folder):
    #the number the next page taken in is saved under: one past the comic's last
    numbers = [page_number(name) for name in os.listdir(folder)
               if name != METADATA_FILE and os.path.isfile(os.path.join(folder, name))]
    held = [number for number in numbers if number is not None]
    return max(held) + 1 if held else len(numbers) + 1


class Namer:
    #names a page as it is taken in: its number, then what it was called. two files are one page to the
    #reader and to every archive when their names agree once the number is put aside (page_key), so a name
    #that would agree with a page the comic holds - a program that calls every chapter's first page 001.jpg,
    #or reuses a name a year later - is told apart with a (2) rather than standing in for the earlier page.
    #nothing taken in ever writes over a file that is there
    def __init__(self, folder):
        self.folder = folder
        self.number = next_number(folder)
        self.keys = set(held_pages(folder))
        self.held = dict((page_key(name), name) for name in os.listdir(folder)
                         if name != METADATA_FILE and os.path.isfile(os.path.join(folder, name)))

    def already_held(self, what, source=None, body=None):
        #the very page the comic has, fetched again by a program that starts from the beginning each time: the
        #same name and the same bytes. a different picture under a name the comic has is a new page
        held = self.held.get(page_key("0000_" + (safe_name(what) or "page")))
        if not held:
            return False
        path = os.path.join(self.folder, held)
        try:
            if body is None:
                if os.path.getsize(source) != os.path.getsize(path):
                    return False
                with open(source, 'rb') as f:
                    body = f.read()
            elif len(body) != os.path.getsize(path):
                return False
            with open(path, 'rb') as f:
                return f.read() == body
        except OSError:
            return False

    def name(self, what):
        #what it was called, made safe; built here rather than with numbered_name, which would strip a
        #program's own leading 001_ and leave a chapter's pages all one page
        stem, ending = os.path.splitext(safe_name(what) or "page")
        candidate, again = stem + ending, 1
        while page_key("{0:04d}_{1}".format(self.number, candidate)) in self.keys or os.path.exists(
                os.path.join(self.folder, "{0:04d}_{1}".format(self.number, candidate))):
            again += 1
            candidate = "{0} ({1}){2}".format(stem, again, ending)
        if again > 1:
            print("WARNING: {0} is already the name of a page of this comic, so it is taken in as {1}".format(
                what, candidate))
        named = "{0:04d}_{1}".format(self.number, candidate)
        self.keys.add(page_key(named))
        self.number += 1
        return named


def newest(staging, paths):
    return max(paths, key=lambda path: os.path.getmtime(os.path.join(staging, path)))


def take_pages(staging, folder, files, cut_short, taken, namer):
    #a program that leaves pages: every picture it wrote, in order. one that sorts its pages into folders
    #keeps that in each page's name, so two folders' 001.jpg are two pages
    infos = sorted((path for path in files if is_comicinfo(path)), key=lambda path: path.count('/'))
    if infos:
        with open(os.path.join(staging, infos[0]), 'rb') as f:
            taken.comicinfo = comicinfo.kept_tags(f.read()) or None
    pictures = [path for path in files if PAGE_TYPES.search(path)]
    if cut_short and pictures:
        last = newest(staging, pictures)
        pictures.remove(last)
        taken.dropped.append((last, HALF_WRITTEN))
    for path in pictures:
        what, source = path.replace('/', ' - '), os.path.join(staging, path.replace('/', os.sep))
        if namer.already_held(what, source=source):
            taken.held += 1
            continue
        name = namer.name(what)
        os.replace(source, os.path.join(folder, name))
        taken.pages.append(name)


def chapter_folders(staging, files, cut_short, taken):
    #a program that leaves a folder of pages per chapter: each folder holding pictures is a chapter, named
    #by the folder. pictures loose in staging itself are in no chapter, and are left out saying so
    chapters = {}
    for path in files:
        if PAGE_TYPES.search(path) or is_comicinfo(path):
            chapters.setdefault(os.path.dirname(path), []).append(path)
    loose = chapters.pop("", [])
    for path in loose:
        taken.dropped.append((path, "is in no chapter's folder"))
    chapters = {where: held for where, held in chapters.items() if any(PAGE_TYPES.search(p) for p in held)}
    if cut_short and chapters:
        last = max(chapters, key=lambda where: max(os.path.getmtime(os.path.join(staging, p))
                                                   for p in chapters[where]))
        taken.dropped.append((last, HALF_WRITTEN))
        del chapters[last]
    found = []
    for where, held in chapters.items():
        info = next((path for path in held if is_comicinfo(path)), None)
        kept = {}
        if info:
            with open(os.path.join(staging, info), 'rb') as f:
                kept = comicinfo.kept_tags(f.read())

        def pages(held=held):
            for path in held:
                if PAGE_TYPES.search(path):
                    yield os.path.basename(path), os.path.join(staging, path.replace('/', os.sep)), None
        found.append((os.path.basename(where), where, kept, pages))
    return found


def chapter_archives(staging, files, taken):
    #a program that leaves an archive per chapter: each is a chapter, named by the archive. one that will
    #not open, or fails its own checks as it is read, was being written when the program stopped, and is
    #left out - the program fetches it again, since where it got to only moves on with what was taken in
    found = []
    for path in files:
        if not ARCHIVES.search(path):
            continue
        full = os.path.join(staging, path.replace('/', os.sep))
        try:
            with zipfile.ZipFile(full) as zf:
                entries = [entry for entry in zf.infolist() if not entry.is_dir()]
                info = next((entry for entry in entries if is_comicinfo(entry.filename)), None)
                kept = comicinfo.kept_tags(zf.read(info)) if info else {}
                pictures = sorted((entry for entry in entries if PAGE_TYPES.search(entry.filename)),
                                  key=lambda entry: sort_key(entry.filename))
                #read whole here, so an archive cut off part way is found out before any of it is taken
                bodies = [(os.path.basename(entry.filename), zf.read(entry)) for entry in pictures]
        except (OSError, zipfile.BadZipFile, zlib.error, EOFError, ValueError) as error:
            taken.dropped.append((path, "will not open as an archive ({0}); {1}".format(error, HALF_WRITTEN)))
            continue

        def pages(bodies=bodies):
            for name, body in bodies:
                yield name, None, body
        found.append((os.path.splitext(os.path.basename(path))[0], path, kept, pages))
    return found


def take_chapters(found, folder, held_labels, order, taken, namer):
    #each chapter not already held, in the order the plugin reads them in, its pages named for it
    by_label = {}
    for label, where, kept, pages in found:
        if label in by_label:
            taken.dropped.append((where, "is a second chapter called {0}".format(label)))
            continue
        by_label[label] = (where, kept, pages)
    labels = list(order(list(by_label)))
    for label in labels:
        where, kept, pages = by_label[label]
        if label in held_labels:
            #a program resuming from the last chapter it got fetches that chapter again
            taken.skipped.append(label)
            continue
        first = None
        for name, source, body in pages():
            what = "{0} - {1}".format(label, name)
            if namer.already_held(what, source, body):
                taken.held += 1
                continue
            named = namer.name(what)
            if source:
                os.replace(source, os.path.join(folder, named))
            else:
                write_page(os.path.join(folder, named), body)
            taken.pages.append(named)
            first = first if first is not None else page_number(named)
        if first is None:
            taken.dropped.append((where, "holds no pictures"))
            continue
        chapter = {"label": label, "start_page": first}
        if kept:
            chapter["comicinfo"] = kept
        taken.chapters.append(chapter)
        held_labels.add(label)


def default_order(labels):
    #chapters in the order their names sort, numbers as numbers, so Chapter 9 comes before Chapter 10
    return sorted(labels, key=sort_key)


def take_in(plugin, folder, metadata, cut_short=False):
    #everything the program left in staging, taken into the comic, and staging cleared after. cut_short is
    #a program stopped part way - by its time running out, or a run before this one killed - whose newest
    #page or chapter may be half written, so it is left for the program to fetch again
    staging = staging_folder(folder)
    taken = Taken()
    if not os.path.isdir(staging):
        return taken
    files = files_under(staging)
    namer = Namer(folder)
    if plugin.output == "pages":
        take_pages(staging, folder, files, cut_short, taken, namer)
    else:
        if plugin.output == "chapter-folders":
            found = chapter_folders(staging, files, cut_short, taken)
        else:
            found = chapter_archives(staging, files, taken)
        held_labels = {chapter.get("label") for chapter in (metadata.get("chapters") or {}).get("list") or []}
        take_chapters(found, folder, held_labels, plugin.hook("chapter_order") or default_order, taken, namer)
    for what, why in taken.dropped:
        print("  left out {0}: it {1}".format(what, why))
    if taken.held:
        print("  {0} page(s) the comic already has, the same files fetched again, not taken again".format(
            taken.held))
    if taken.skipped:
        print("  {0} chapter(s) the comic already has, not taken again: {1}".format(
            len(taken.skipped), ", ".join(taken.skipped[:5]) + (" ..." if len(taken.skipped) > 5 else "")))
    shutil.rmtree(staging, ignore_errors=True)
    return taken


def record_chapters(folder, metadata, new):
    #the chapters just taken in, added to the comic's list, each running until the next one starts. False
    #when the comic's files cannot say which is which page - a file put in by hand with no number - since
    #a list worked out from them then would cut chapters in the wrong places
    if not new:
        return True
    block = metadata.get("chapters") or {}
    pages, why = numbered_pages(folder)
    if pages is None:
        print("WARNING: the chapters just taken in were not added to the comic's list, since {0}. Give "
              "every file in {1} the number of the page it is, then run it again.".format(why, folder))
        return False
    found = [dict(chapter) for chapter in block.get("list") or []] + [dict(chapter) for chapter in new]
    metadata["chapters"] = chapters_block(block, settle_chapters(found, pages), "plugin")
    return True


def remember(plugin, state, taken):
    #where the program got to, for building its next command: by default the last chapter and the last
    #page taken in, which a plugin.json command can name as {last_chapter} and {last_page}
    own = plugin.hook("remember")
    if own is not None:
        return own(dict(state or {}), taken.view())
    state = dict(state or {})
    if taken.chapters:
        state["last_chapter"] = taken.chapters[-1]["label"]
    if taken.pages:
        state["last_page"] = taken.pages[-1]
    return state
