#packing a comic's pages into .cbz archives. every archive any script writes goes through here, so a page
#no reader can show gets the same stand-in whether the comic keeps one archive or one per chapter, and
#whether the archive is added to after a scrape or written afresh.
import os
import zipfile

from comiclib.metadata import METADATA_FILE
from comiclib.standin import archive_entry

#the Compress-Archive name for the tree beside a library's loose pages
PAGES_TREE = "uncompressed"
SHELF = "CBZs"


def archive_prefix(zf, folder):
    #archives built by Compress-Archive put every entry under the folder name, while a plain zip of the
    #contents does not. new entries have to match whichever this archive already uses, or a reader shows
    #the comic as two separate groups
    prefix = os.path.basename(os.path.abspath(folder)) + '/'
    names = zf.namelist()
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


def expected(folder, names):
    #what an archive of these files should hold, as entry name to size: the file itself, or its stand-in,
    #which is drawn the same way every time, so its size is what says it is already there
    wanted = {}
    for name in names:
        entry, made = archive_entry(folder, name)
        wanted[entry] = len(made) if made is not None else os.path.getsize(os.path.join(folder, name))
    return wanted


def held(cbz):
    #what an archive holds, as entry name to size, leaving out folders
    with zipfile.ZipFile(cbz) as zf:
        return {info.filename: info.file_size for info in zf.infolist() if not info.filename.endswith('/')}


def write(cbz, folder, names, prefix='', first=()):
    #an archive written afresh from these files, in this order, each as itself or as its stand-in. `first`
    #is (entry, bytes) written ahead of them - a ComicInfo.xml. written aside and moved into place, so a
    #run stopped halfway leaves the old archive, or none, rather than half of a new one.
    parent = os.path.dirname(cbz)
    if parent:
        os.makedirs(parent, exist_ok=True)
    spare = cbz + ".packing"
    try:
        #images are already compressed, so storing them saves the cpu for no meaningful size difference
        with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
            for entry, body in first:
                zf.writestr(entry, body)
            for name in names:
                entry, made = archive_entry(folder, name)
                if made is None:
                    zf.write(os.path.join(folder, name), prefix + entry)
                else:
                    zf.writestr(prefix + entry, made)
        os.replace(spare, cbz)
    except (OSError, zipfile.BadZipFile):
        if os.path.exists(spare):
            try:
                os.remove(spare)
            except OSError:
                pass
        raise
    return len(names)


def append(cbz, folder, pages, superseded=()):
    #adds to an archive the pages it does not hold yet. a zip keeps its entries in the order they were
    #written and rewrites only the directory at the end, so appending leaves every existing byte where it
    #is and a sync has to carry no more than the new pages. the metadata is written again, last, and
    #anything named in `superseded` - a page whose filename was replaced - leaves the directory.
    #
    #read first, so an archive with nothing to add is left untouched rather than having its directory
    #rewritten, which would make a sync re-checksum the whole file for no reason
    with zipfile.ZipFile(cbz) as zf:
        prefix = archive_prefix(zf, folder)
        existing = set(zf.namelist())
    #a page held otherwise counts as present when its stand-in is there, not when the file is
    added = [name for name in pages if prefix + archive_entry(folder, name)[0] not in existing]
    #a page whose filename was replaced has to leave the archive under its old name too, or the comic
    #shows that page twice for good
    stale_pages = [prefix + name for name in superseded if prefix + name in existing]
    if not added and not stale_pages:
        return 0

    with zipfile.ZipFile(cbz, 'a', zipfile.ZIP_STORED) as zf:
        meta_name = prefix + METADATA_FILE
        last_offset = max((i.header_offset for i in zf.infolist()), default=0)
        internals = all(hasattr(zf, attr) for attr in ('filelist', 'NameToInfo', 'start_dir'))
        if internals:
            for name in stale_pages:
                gone = zf.NameToInfo.get(name)
                if gone is None:
                    continue
                #the bytes stay where they are and simply stop being referenced, which no reader looks
                #at; only the directory has to forget the name
                zf.filelist.remove(gone)
                del zf.NameToInfo[name]
                print("Removed the superseded {0} from the archive.".format(name))
        stale = zf.NameToInfo.get(meta_name)
        if stale is not None and internals:
            #drop the old copy from the directory so the refreshed one does not leave a duplicate entry.
            #the metadata is always written last, so its bytes can usually be reclaimed; in an archive
            #built elsewhere it may sit anywhere, and those few bytes are simply left unreferenced, which
            #no reader ever looks at.
            was_last = stale.header_offset == last_offset
            zf.filelist.remove(stale)
            del zf.NameToInfo[meta_name]
            if was_last:
                zf.start_dir = stale.header_offset
        for name in added:
            entry, made = archive_entry(folder, name)
            if made is None:
                zf.write(os.path.join(folder, name), prefix + entry)
            else:
                zf.writestr(prefix + entry, made)
        if os.path.isfile(os.path.join(folder, METADATA_FILE)):
            zf.write(os.path.join(folder, METADATA_FILE), meta_name)
    return len(added)
