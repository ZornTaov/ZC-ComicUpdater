#packing a comic's pages into .cbz archives. every archive any script writes goes through here, so a page
#no reader can show gets the same stand-in whether the comic keeps one archive or one per chapter, and
#whether the archive is added to after a scrape or written afresh - and every one carries a ComicInfo.xml
#saying what it is, kept as current as its pages.
import os
import zipfile

from comiclib import comicinfo
from comiclib.metadata import METADATA_FILE
from comiclib.pages import PAGE_TYPES, reading_order
from comiclib.standin import archive_entry, held_otherwise

#the Compress-Archive name for the tree beside a library's loose pages
PAGES_TREE = "uncompressed"
SHELF = "CBZs"


def archive_prefix(zf, folder):
    #archives built by Compress-Archive put every entry under the folder name, while a plain zip of the
    #contents does not. new entries have to match whichever this archive already uses, or a reader shows
    #the comic as two separate groups
    #the ComicInfo is at the top of every archive whatever its pages are under, since that is where a
    #reader looks for it, so it says nothing about where the pages are
    prefix = os.path.basename(os.path.abspath(folder)) + '/'
    names = [name for name in zf.namelist() if name != comicinfo.NAME]
    return prefix if names and all(name.startswith(prefix) for name in names) else ''


def shelf(folder):
    #where this library keeps its archives: a comic under an Uncompressed tree belongs in the CBZs tree
    #beside it. (pages tree, shelf), or (None, None) for a folder that is not laid out that way
    parts = os.path.abspath(folder).replace('\\', '/').split('/')
    #the last part is the comic itself and the first is the drive or root, so neither can be the tree
    for at in range(len(parts) - 2, 0, -1):
        if parts[at].lower() != PAGES_TREE:
            continue
        found = os.sep.join(parts[:at] + [SHELF])
        if os.path.isdir(found):
            return os.sep.join(parts[:at + 1]), found
    return None, None


def default_path(folder):
    #where a comic's archive goes when nothing says. a library that keeps its pages under an Uncompressed
    #folder and its archives in a matching CBZs tree gets them filed there, so the plain command puts a new
    #comic where the reader is already looking rather than among the loose pages.
    folder = os.path.abspath(folder)
    beside = folder + '.cbz'
    if os.path.exists(beside):
        #an archive already sitting next to its folder keeps its place. filing it somewhere new would
        #start a second archive and leave the reader pointed at one that quietly stops growing.
        return beside
    tree, found = shelf(folder)
    if found:
        below = os.path.relpath(folder, tree)
        return os.path.join(found, below) + '.cbz'
    return beside


def expected(folder, names, sizes=None):
    #what an archive of these files should hold, as entry name to size: the file itself, or its stand-in,
    #which is drawn the same way every time, so its size is what says it is already there. sizes, when given,
    #is every file's size from one listing of the folder, so a comic of thousands is not asked file by file
    wanted = {}
    for name in names:
        entry, made = archive_entry(folder, name)
        if made is not None:
            wanted[entry] = len(made)
        else:
            wanted[entry] = sizes[name] if sizes and name in sizes else os.path.getsize(os.path.join(folder, name))
    return wanted


def held(cbz):
    #what an archive holds of the comic's folder, as entry name to size: leaving out folders, and the
    #ComicInfo, which is written for the archive and is no file of the comic's
    with zipfile.ZipFile(cbz) as zf:
        return {info.filename: info.file_size for info in zf.infolist()
                if not info.filename.endswith('/') and info.filename != comicinfo.NAME}


def page_order(entries, prefix):
    #the entries a reader turns through as pages, in the order it reads them: pictures directly under the
    #prefix, ordered the way the comic's folder is. a ComicInfo numbers its pages in this order
    names = {entry[len(prefix):]: entry for entry in entries
             if entry.startswith(prefix) and '/' not in entry[len(prefix):] and PAGE_TYPES.search(entry)}
    return [names[name] for name in reading_order(None, list(names))]


def standins(folder, names, prefix=''):
    #the entries that are a stand-in for a page no reader can show, so ComicInfo can say they are not story
    return {prefix + archive_entry(folder, name)[0] for name in names if held_otherwise(folder, name)}


def head_of(zf, info):
    #the first bytes of an entry, for measuring it, without reading the whole page
    def read(n):
        with zf.open(info) as f:
            return f.read(n)
    return read


def described(zf, prefix):
    #each page as the archive's ComicInfo already says it is, by entry, so a page is measured once and not
    #every time the archive is added to. only believed where the ComicInfo describes as many pages as there
    #are, and each is still the size it said: a ComicInfo some other tool wrote, or one older than a page
    #replaced by hand, is not taken on trust
    try:
        said = comicinfo.pages_said(zf.read(comicinfo.NAME))
    except KeyError:
        return {}
    entries = page_order([info.filename for info in zf.infolist() if not info.is_dir()], prefix)
    if len(said) != len(entries):
        return {}
    return {entry: each for entry, each in zip(entries, said) if each["size"] == zf.getinfo(entry).file_size}


def info_for(about, facts, prefix):
    #the ComicInfo for an archive whose pages are `facts`, entry to page(), however many other files it holds
    return comicinfo.build(about, [facts[entry] for entry in page_order(list(facts), prefix)])


def write(cbz, folder, names, prefix='', about=None):
    #an archive written afresh from these files, in this order, each as itself or as its stand-in, then the
    #ComicInfo saying what it is - `about`, or the whole comic when it says nothing - and the metadata last,
    #so a scrape adding to it later can take both back and write them again after its pages. written aside
    #and moved into place, so a run stopped halfway leaves the old archive, or none, rather than half of a
    #new one.
    parent = os.path.dirname(cbz)
    if parent:
        os.makedirs(parent, exist_ok=True)
    spare = cbz + ".packing"
    facts = {}
    try:
        #images are already compressed, so storing them saves the cpu for no meaningful size difference
        with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
            for name in [name for name in names if name != METADATA_FILE]:
                entry, made = archive_entry(folder, name)
                path = os.path.join(folder, name)
                if made is not None:
                    zf.writestr(prefix + entry, made)
                    facts[prefix + entry] = comicinfo.page(len(made), comicinfo.dimensions(made), True)
                elif PAGE_TYPES.search(name):
                    #a page is read once, both to measure and to store, rather than opened twice on a share
                    with open(path, 'rb') as f:
                        body = f.read()
                    zf.writestr(zipfile.ZipInfo.from_file(path, prefix + entry), body)
                    facts[prefix + entry] = comicinfo.page(len(body), comicinfo.measure(lambda n: body[:n]), False)
                else:
                    zf.write(path, prefix + entry)
            zf.writestr(comicinfo.NAME, info_for(about or comicinfo.about_comic(folder), facts, prefix))
            if METADATA_FILE in names:
                zf.write(os.path.join(folder, METADATA_FILE), prefix + METADATA_FILE)
        os.replace(spare, cbz)
    except (OSError, zipfile.BadZipFile):
        if os.path.exists(spare):
            try:
                os.remove(spare)
            except OSError:
                pass
        raise
    return len(names)


def append(cbz, folder, pages, superseded=(), about=None):
    #adds to an archive the pages it does not hold yet. a zip keeps its entries in the order they were
    #written and rewrites only the directory at the end, so appending leaves every existing byte where it
    #is and a sync has to carry no more than the new pages. the ComicInfo and the metadata are written
    #again, last, and anything named in `superseded` - a page whose filename was replaced - leaves the
    #directory. an archive with nothing to add, whose ComicInfo already says what it should, is left
    #untouched rather than having its directory rewritten, which would make a sync re-checksum the whole
    #file for no reason
    change = planned(cbz, folder, pages, superseded, about or comicinfo.about_comic(folder))
    if change["added"] or change["stale"] or change["retold"]:
        apply(cbz, folder, change, metadata=True)
    return len(change["added"])


def retag(cbz, folder, names, about, dry_run=False):
    #brings a chapter archive's ComicInfo up to what it should say - a label put right, the comic marked
    #ended - without writing its pages again: the new ComicInfo goes on the end, as an append's does.
    #True when it said something else
    change = planned(cbz, folder, names, (), about, adding=False)
    if not change["retold"]:
        return False
    if not dry_run:
        apply(cbz, folder, change, metadata=False)
    return True


def planned(cbz, folder, pages, superseded, about, adding=True):
    #what adding to an archive would change: the files it does not hold yet, the superseded entries to
    #forget, the ComicInfo it should end up with, and whether that says anything the one it has does not
    with zipfile.ZipFile(cbz) as zf:
        prefix = archive_prefix(zf, folder)
        existing = set(zf.namelist())
        #a page held otherwise counts as present when its stand-in is there, not when the file is. not
        #adding, the archive is described as it is, whatever the folder holds that it does not
        added = [name for name in pages if prefix + archive_entry(folder, name)[0] not in existing] if adding else []
        #a page whose filename was replaced has to leave the archive under its old name too, or the comic
        #shows that page twice for good
        stale = [prefix + name for name in superseded if prefix + name in existing]
        known = described(zf, prefix)
        drawn = standins(folder, pages, prefix)
        facts = {}
        for entry in page_order([name for name in existing if name not in stale], prefix):
            if entry in known:
                facts[entry] = dict(known[entry], standin=known[entry]["standin"] or entry in drawn)
            else:
                #measured from the archive itself, so a comic whose loose pages are gone is described too
                info = zf.getinfo(entry)
                facts[entry] = comicinfo.page(info.file_size, comicinfo.measure(head_of(zf, info)), entry in drawn)
        try:
            had = zf.read(comicinfo.NAME)
        except KeyError:
            had = None
    for name in added:
        entry, made = archive_entry(folder, name)
        if made is not None:
            facts[prefix + entry] = comicinfo.page(len(made), comicinfo.dimensions(made), True)
        elif PAGE_TYPES.search(name):
            path = os.path.join(folder, name)

            def read(n, path=path):
                with open(path, 'rb') as f:
                    return f.read(n)
            facts[prefix + entry] = comicinfo.page(os.path.getsize(path), comicinfo.measure(read), False)
    info = info_for(about, facts, prefix)
    return {"prefix": prefix, "added": added, "stale": stale, "info": info, "retold": info != had}


def apply(cbz, folder, change, metadata):
    prefix = change["prefix"]
    with zipfile.ZipFile(cbz, 'a', zipfile.ZIP_STORED) as zf:
        meta_name = prefix + METADATA_FILE
        internals = all(hasattr(zf, attr) for attr in ('filelist', 'NameToInfo', 'start_dir'))
        if internals:
            for name in change["stale"]:
                gone = zf.NameToInfo.get(name)
                if gone is None:
                    continue
                #the bytes stay where they are and simply stop being referenced, which no reader looks
                #at; only the directory has to forget the name
                zf.filelist.remove(gone)
                del zf.NameToInfo[name]
                print("Removed the superseded {0} from the archive.".format(name))
            #the ComicInfo and the metadata are written again after everything else, so the old copies
            #leave the directory or the archive would hold each twice. they are always written last, so
            #their bytes can usually be reclaimed: whatever of them comes after every entry staying is
            #written over. in an archive built elsewhere they may sit anywhere, and those few bytes are
            #simply left unreferenced, which no reader ever looks at.
            renewed = [comicinfo.NAME] + ([meta_name] if metadata else [])
            going = [zf.NameToInfo[name] for name in renewed if name in zf.NameToInfo]
            for info in going:
                zf.filelist.remove(info)
                del zf.NameToInfo[info.filename]
            staying = max((info.header_offset for info in zf.filelist), default=-1)
            after = [info.header_offset for info in going if info.header_offset > staying]
            if after:
                zf.start_dir = min(after)
        for name in change["added"]:
            entry, made = archive_entry(folder, name)
            if made is None:
                zf.write(os.path.join(folder, name), prefix + entry)
            else:
                zf.writestr(prefix + entry, made)
        #where nothing could be taken out of the directory, a second ComicInfo would only be a duplicate
        if internals or comicinfo.NAME not in zf.NameToInfo:
            zf.writestr(comicinfo.NAME, change["info"])
        if metadata and os.path.isfile(os.path.join(folder, METADATA_FILE)):
            zf.write(os.path.join(folder, METADATA_FILE), meta_name)
