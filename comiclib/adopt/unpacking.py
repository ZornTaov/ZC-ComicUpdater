#a comic that exists only as one archive, made into a folder of pages: what is safe to take out of it, the
#taking out, and - for an archive already in the library - adopting what came out. a comic kept only as an
#archive can be carried on, but not lined up against its walk or cut into chapters, which both work on the
#files in its folder.
import os
import posixpath
import re
import shutil
import zipfile

from comiclib.adopt.adopting import adopt_one
from comiclib.adopt.scan import is_page, relative_output
from comiclib.metadata import METADATA_FILE

#read and written a megabyte at a time, so a file of gigabytes never sits in memory
CHUNK = 1 << 20


class Refused(Exception):
    #why an archive cannot go in, said so the reader knows what to change
    pass


def pages_folder(names):
    #the one folder inside an archive that holds its pages, from the archive's own list of what it holds
    unsafe = [name for name in names
              if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/")]
    if unsafe:
        raise Refused("it holds a path that would land outside its own folder, {0}".format(unsafe[0]))
    pages = [name for name in names if is_page(name)]
    if not pages:
        raise Refused("there are no pages in it")
    #a comic here is one folder of pages. pages spread over several - a comic and its extras, kept apart
    #by whoever made the archive - have no single order to be read in, which is for the reader to settle
    folders = sorted({posixpath.dirname(name) for name in pages})
    if len(folders) > 1:
        raise Refused("its pages are in {0} different folders ({1}). Put them in one folder, or bring each "
                      "in as a comic of its own".format(len(folders), ", ".join(f or "the top" for f in folders[:4])))
    return folders[0]


def unpack(path, inner, staging, cancel=None):
    #the pages and the settings, flat into staging. everything else in the archive stays behind
    os.makedirs(staging, exist_ok=True)
    done = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or posixpath.dirname(name) != inner:
                continue
            base = posixpath.basename(name)
            if not (is_page(base) or base == METADATA_FILE):
                continue
            with archive.open(info) as source, open(os.path.join(staging, base), "wb") as out:
                shutil.copyfileobj(source, out, CHUNK)
            done += 1
            if done % 500 == 0:
                print("  unpacked {0} file(s)".format(done), flush=True)
                if cancel is not None and cancel.is_set():
                    raise Refused("stopped part way through unpacking; nothing was put in the library")
    return done


def unpack_and_adopt(args):
    #an archive already on the library's shelf, unpacked into the folder it names and adopted there, with
    #the archive kept as the comic's own. returns (written, message), as adopt_one does
    archive = os.path.abspath(args.path)
    target = os.path.abspath(os.path.join(args.root, args.unpack_to))
    if not (os.path.isfile(archive) and archive.lower().endswith(".cbz")):
        return False, "--unpack-to unpacks a .cbz, and {0} is not one".format(args.path)
    #everything that could stop it is asked before anything is written, so a refusal leaves no half-made
    #folder behind
    if not args.ended and not (args.last_url or args.next_url):
        return False, "needs an address, or ended"
    if os.path.isdir(target) and os.listdir(target):
        return False, "{0} already holds files; unpack into a folder of its own".format(args.unpack_to)
    if os.path.exists(os.path.join(target, METADATA_FILE)):
        return False, "{0} is already a comic".format(args.unpack_to)
    try:
        with zipfile.ZipFile(archive) as opened:
            names = [info.filename.replace("\\", "/") for info in opened.infolist() if not info.is_dir()]
        inner = pages_folder(names)
    except (Refused, zipfile.BadZipFile, OSError) as error:
        return False, "cannot unpack {0}: {1}".format(args.path, error)
    if any(posixpath.basename(name) == METADATA_FILE for name in names):
        #one that was adopted once already carries its settings, which say more than a fresh adoption can
        return False, ("it already carries a {0}; upload it through the web page, which keeps the settings "
                       "it came with".format(METADATA_FILE))
    if args.dry_run:
        return False, "would unpack {0} page(s) into {1} and adopt them".format(
            len([name for name in names if posixpath.dirname(name) == inner and is_page(name)]), args.unpack_to)

    #unpacked beside where it goes and moved in whole, so an interrupted unpack leaves nothing that looks
    #like a comic. a dot in front keeps the library scan from taking it for one while it fills
    staging = os.path.join(os.path.dirname(target), "." + os.path.basename(target) + ".unpacking")
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    print("Unpacking {0} into {1}".format(args.path, args.unpack_to), flush=True)
    count = unpack(archive, inner, staging)
    if os.path.isdir(target):
        os.rmdir(target)
    os.replace(staging, target)
    print("  unpacked {0} file(s)".format(count), flush=True)

    args.path = target
    args.cbz_path = relative_output(archive, args.root)
    args.make_cbz = False
    args.force = False
    ok, outcome = adopt_one(args)
    if not ok:
        return False, "unpacked into {0}, but adopting it failed: {1}".format(args.unpack_to, outcome)
    return True, outcome
