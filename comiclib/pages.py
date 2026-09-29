#what a page's filename says about it: which page it is, however it was spelled, and where it sits.
import os
import re

from comiclib.metadata import METADATA_FILE
from comiclib.standin import held_otherwise

#what a reader can show as a page
PAGE_TYPES = re.compile(r'\.(png|jpe?g|gif|webp|bmp)$', re.I)
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


def saved_name(src, file_format="png"):
    #the name a scrape gives an image: the last part of its address, with an extension added where the
    #address has none. a gif stays a gif. every file a scrape writes is named by this, so anything that
    #needs to know what a page will be called - the index, a page put in by hand - asks here.
    #the image is fetched with requests rather than saved by a browser, so nothing strips a query string
    #or a fragment on the way: that is done here, since page.png?v=2 is page.png, and a ? cannot be in a
    #filename on windows at all
    if "gif" in src:
        file_format = "gif"
    path = src.split('#')[0].split('?')[0].rstrip('/')
    name = path[path.rfind("/") + 1:]
    return name if name.lower().endswith(file_format) else "{0}.{1}".format(name, file_format)


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
