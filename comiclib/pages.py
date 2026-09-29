#what a page's filename says about it: which page it is, however it was spelled, and where it sits.
import email.message
import os
import re

from comiclib.metadata import METADATA_FILE
from comiclib.standin import held_otherwise

#what a reader can show as a page
PAGE_TYPES = re.compile(r'\.(png|jpe?g|gif|webp|bmp|avif)$', re.I)
#the number a page was saved under: 0742_something.jpg, or a plain 0742.jpg
NUMBERED = re.compile(r'^(\d+)(?:[._])')


def page_key(name):
    #what makes two filenames the same page, ignoring how each happened to be named: the '0742_' a scrape
    #adds in front moves whenever a comic is renumbered, and an extension has been appended to names that
    #already had one. so '0742_a-page.png.png' and 'a-page.png' are one page.
    #a number followed by a dot is NOT stripped - for a comic whose pages the site names '0005.gif', that
    #number is the only thing telling one page from another.
    stem = re.sub(r'^\d{3,}_', '', name)
    stem = re.sub(r'\.(png|jpe?g|gif|webp)\.(png|jpe?g|gif|webp)$', r'.\1', stem, flags=re.I)
    return stem.lower()


def page_number(name):
    #the page number a filename carries, from the prefix a scrape adds or from a name that is just the
    #number. none when the name says nothing about where the page sits.
    found = NUMBERED.match(name)
    return int(found.group(1)) if found else None


def sort_key(name):
    #numbers sort as numbers, so 9 comes before 10 for a comic whose files were never padded
    return [int(bit) if bit.isdigit() else bit.lower() for bit in re.split(r'(\d+)', name)]


def plain_name(name):
    #a name a scrape has already numbered, back to whatever the site called it
    return re.sub(r'^\d{1,6}_', '', name)


def numbered_name(number, name):
    #the name a page gets once it carries its number, whatever it carried before
    return "{0:04d}_{1}".format(number, plain_name(name))


def saved_name(src, headers=None, body=None):
    #the name a page is saved under: what the site says the file is called. every file a scrape writes is
    #named by this, so anything that needs to know what a page is called - the index, a page put in by
    #hand - asks here.
    #
    #the server's own word first: a Content-Disposition filename is the site saying outright what the file
    #is. failing that, the last part of the image's address, without its query or fragment - the image is
    #fetched with requests, not saved by a browser, so nothing strips those on the way, and a site serving
    #every image as /comic-image/1650564/?token=... would otherwise have its token saved as the name.
    #
    #nothing is ever added to a name that already says what it is: a jpg is saved as a jpg. only a name
    #with no picture extension at all gets one, from Content-Type or failing that the file's own first
    #bytes, since a reader looking inside an archive goes by the extension to know an entry is a picture.
    #headers and body are what the fetch returned; without them - a walk, which downloads nothing - the
    #address is all there is to go on.
    name = disposition_name(headers) or address_name(src)
    if not PICTURE.search(name):
        kind = type_from_headers(headers) or type_from_bytes(body)
        if kind:
            name = "{0}.{1}".format(name, kind)
    return name


#what counts as already saying what the file is: a picture, or a page kept some other way
PICTURE = re.compile(r'\.(png|jpe?g|gif|webp|bmp|avif|mp4|m4v|webm|mov|mkv|swf)$', re.I)
#the extension each picture type is saved with, when the name the site gave says nothing
KINDS = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/pjpeg": "jpg",
         "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp", "image/avif": "avif"}


def address_name(src):
    #the last part of an image's address, without its query or fragment
    path = (src or "").split('#')[0].split('?')[0].rstrip('/')
    return safe_name(path[path.rfind("/") + 1:]) or "page"


def disposition_name(headers):
    #the filename a server gives in Content-Disposition, in either of the ways it can be written - plain,
    #or the encoded filename*= form - which the standard library's mail parser already reads
    value = (headers or {}).get("Content-Disposition")
    if not value:
        return None
    parsed = email.message.Message()
    parsed["Content-Disposition"] = value
    try:
        given = parsed.get_filename()
    except (ValueError, LookupError):
        return None
    #a server is not to be trusted with a path: only the last part of whatever it says is a name
    return safe_name(re.split(r'[\\/]', given)[-1]) if given else None


def safe_name(name):
    #a name every filesystem the library might sit on will take: nothing windows refuses, and not ending in
    #the dot or space windows silently drops
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or "").rstrip(" .")


def type_from_headers(headers):
    kind = ((headers or {}).get("Content-Type") or "").split(";")[0].strip().lower()
    return KINDS.get(kind)


def type_from_bytes(body):
    #the signature every picture format starts with, for a server that does not say what it sent
    head = bytes(body or b"")[:12]
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"GIF8"):
        return "gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"BM"):
        return "bmp"
    return None


def held_pages(folder):
    #what is on disk already, as page identity to page number, so a page is recognised however it was
    #named last time and its position is known. every file counts - a page held as a video is still a
    #page - except the metadata.
    held = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return held
    for name in names:
        if name == METADATA_FILE or not os.path.isfile(os.path.join(folder, name)):
            continue
        held.setdefault(page_key(name), page_number(name))
    return held


def listing(folder, others=False):
    #the comic's pages as files, in reading order. a page held as a video, as flash, or as a note saying
    #where it lives now is asked for only where a page has to be accounted for - the lining up, and the
    #packing that puts a stand-in in its place
    names = [f for f in os.listdir(folder)
             if (PAGE_TYPES.search(f) or (others and held_otherwise(folder, f)))
             and os.path.isfile(os.path.join(folder, f))]
    return reading_order(folder, names)


def reading_order(folder, names):
    #the order the comic reads in: by the number a scrape saved it under where every page has one, and by
    #name otherwise. the number is the order pages were fetched, which is the order they were published.
    if names and all(page_number(name) is not None for name in names):
        return sorted(names, key=lambda name: (page_number(name), sort_key(name)))
    return sorted(names, key=sort_key)


def count(folder):
    #how many files the comic holds, for the progress a run reports while it goes
    try:
        return len([f for f in os.listdir(folder) if f != METADATA_FILE])
    except OSError:
        return 0
