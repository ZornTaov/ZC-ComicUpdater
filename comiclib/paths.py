#where the settings live, and what a comic's index file is called. settings sit beside the scripts rather
#than in the library: they describe the setup, not the comics.
import hashlib
import os
import re

#the folder holding the scripts, which is where the config folder is unless told otherwise
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELEMENT_FILE = "element_paths.json"


def config_folder():
    #MIRROR_CONFIG names it outright, which is how update_comics passes its own --config down to every
    #scrape it starts, and how a test keeps its settings apart from the real ones
    return os.environ.get("MIRROR_CONFIG") or os.path.join(PROJECT, "config")


def index_folder():
    return os.path.join(config_folder(), "index")


def element_paths_file():
    #MIRROR_ELEMENTS names the file outright; otherwise it is the one in the config folder. the two older
    #places - the folder a scrape runs from, and beside the scripts - are still read if nothing else is
    #there, so a library that kept its file in either goes on working.
    named = os.environ.get("MIRROR_ELEMENTS")
    if named:
        return named
    for path in (os.path.join(config_folder(), ELEMENT_FILE),
                 os.path.join(os.getcwd(), ELEMENT_FILE),
                 os.path.join(PROJECT, ELEMENT_FILE)):
        if os.path.exists(path):
            return path
    return os.path.join(config_folder(), ELEMENT_FILE)


def index_name(folder):
    #the comic's own folder decides the name, and nothing else: which library it was reached through must
    #never change which index a comic uses. the short tag is what keeps two comics called Extras apart.
    #one rule for mirror_base, which keeps the index up to date while scraping, and chapters, which walks
    #for it and reads it - named apart once, every walk wrote the wrong file and nothing matched by name.
    full = os.path.abspath(folder)
    tag = hashlib.sha1(full.replace(os.sep, '/').lower().encode('utf-8')).hexdigest()[:8]
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(full)).strip('_') or "comic"
    return "{0}.{1}.jsonl".format(stem, tag)
