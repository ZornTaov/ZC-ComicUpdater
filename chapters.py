#works out which saved file came from which page of a comic, by walking the comic without downloading
#anything and lining that walk up against what is already on disk. the walk is the slow part and its
#result is cached; the alignment is what everything about chapters is later built on. #V 1.0

import argparse
import collections
import hashlib
import json
import os
import re
import html.parser
import shutil
import subprocess
import sys
from urllib.parse import urljoin
import struct
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

import requests

metadata_file = "mirror_metadata.json"
page_types = re.compile(r'\.(png|jpe?g|gif|webp|bmp)$', re.I)
#a page can be held as something no reader can show: a recording of a page that animated, a flash file
#from before flash went away, or a note saying where the page lives now. it is still that page, so the
#lining up has to see it - and the archive gets a stand-in saying where the real thing is.
video_types = re.compile(r'\.(mp4|m4v|webm|mov|mkv)$', re.I)
flash_types = re.compile(r'\.swf$', re.I)
link_types = re.compile(r'\.(txt|url|webloc)$', re.I)
#not anchored: a note can run its own words straight into the address, and wapsisquare's do
a_web_address = re.compile(r'(https?://\S+)')
#the number this script gave a page when it saved it: 0742_something.jpg, or a plain 0742.jpg
numbered = re.compile(r'^(\d+)(?:[._])')


def config_folder():
    return os.environ.get("MIRROR_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config")


def page_key(name):
    #two spellings of one page have to agree: the prefix this script adds is dropped, and an extension
    #appended twice is collapsed. a number followed by a dot is left alone - for a comic whose pages are
    #named 0005.gif that number is the page's whole identity.
    stem = re.sub(r'^\d{3,}_', '', name)
    stem = re.sub(r'\.(png|jpe?g|gif|webp)\.(png|jpe?g|gif|webp)$', r'.\1', stem, flags=re.I)
    return stem.lower()


def page_number(name):
    found = numbered.match(name)
    return int(found.group(1)) if found else None


def sort_key(name):
    #numbers sort as numbers, so 9 comes before 10 for a comic whose files were never padded
    return [int(bit) if bit.isdigit() else bit.lower() for bit in re.split(r'(\d+)', name)]


#five columns and seven rows of dots per letter, written out rather than packed into numbers so that a
#letter that comes out wrong is a letter you can see is wrong. a nine keeps a straight stem and a g hooks
#to the left, because a video's address must not be readable two ways.
GLYPHS = {
    ' ': "...../...../...../...../...../...../.....",
    '!': "..#../..#../..#../..#../..#../...../..#..",
    '"': ".#.#./.#.#./...../...../...../...../.....",
    '#': ".#.#./.#.#./#####/.#.#./#####/.#.#./.#.#.",
    '$': "..#../.####/#.#../.###./..#.#/####./..#..",
    '%': "##.../##..#/...#./..#../.#.../#..##/...##",
    '&': ".##../#..#./#.#../.#.../#.#.#/#..#./.##.#",
    "'": "..#../..#../...../...../...../...../.....",
    '(': "...#./..#../.#.../.#.../.#.../..#../...#.",
    ')': ".#.../..#../...#./...#./...#./..#../.#...",
    '*': "...../#.#.#/.###./#####/.###./#.#.#/.....",
    '+': "...../..#../..#../#####/..#../..#../.....",
    ',': "...../...../...../...../...../..#../.#...",
    '-': "...../...../...../#####/...../...../.....",
    '.': "...../...../...../...../...../.##../.##..",
    '/': "....#/...#./..#../..#../.#.../#..../#....",
    '0': ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    '1': "..#../.##../..#../..#../..#../..#../.###.",
    '2': ".###./#...#/....#/...#./..#../.#.../#####",
    '3': "#####/...#./..#../...#./....#/#...#/.###.",
    '4': "...#./..##./.#.#./#..#./#####/...#./...#.",
    '5': "#####/#..../####./....#/....#/#...#/.###.",
    '6': "..##./.#.../#..../####./#...#/#...#/.###.",
    '7': "#####/....#/...#./..#../.#.../.#.../.#...",
    '8': ".###./#...#/#...#/.###./#...#/#...#/.###.",
    '9': ".###./#...#/#...#/.####/....#/....#/....#",
    ':': "...../.##../.##../...../.##../.##../.....",
    ';': "...../.##../.##../...../.##../..#../.#...",
    '<': "...#./..#../.#.../#..../.#.../..#../...#.",
    '=': "...../...../#####/...../#####/...../.....",
    '>': ".#.../..#../...#./....#/...#./..#../.#...",
    '?': ".###./#...#/....#/...#./..#../...../..#..",
    '@': ".###./#...#/#.###/#.#.#/#.###/#..../.###.",
    'A': "..#../.#.#./#...#/#...#/#####/#...#/#...#",
    'B': "####./#...#/#...#/####./#...#/#...#/####.",
    'C': ".###./#...#/#..../#..../#..../#...#/.###.",
    'D': "###../#..#./#...#/#...#/#...#/#..#./###..",
    'E': "#####/#..../#..../####./#..../#..../#####",
    'F': "#####/#..../#..../####./#..../#..../#....",
    'G': ".###./#...#/#..../#.###/#...#/#...#/.####",
    'H': "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    'I': ".###./..#../..#../..#../..#../..#../.###.",
    'J': "....#/....#/....#/....#/#...#/#...#/.###.",
    'K': "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    'L': "#..../#..../#..../#..../#..../#..../#####",
    'M': "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    'N': "#...#/#...#/##..#/#.#.#/#..##/#...#/#...#",
    'O': ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    'P': "####./#...#/#...#/####./#..../#..../#....",
    'Q': ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    'R': "####./#...#/#...#/####./#.#../#..#./#...#",
    'S': ".####/#..../#..../.###./....#/....#/####.",
    'T': "#####/..#../..#../..#../..#../..#../..#..",
    'U': "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    'V': "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    'W': "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#",
    'X': "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    'Y': "#...#/#...#/.#.#./..#../..#../..#../..#..",
    'Z': "#####/....#/...#./..#../.#.../#..../#####",
    '[': ".###./.#.../.#.../.#.../.#.../.#.../.###.",
    '\\': "#..../#..../.#.../..#../..#../...#./....#",
    ']': ".###./...#./...#./...#./...#./...#./.###.",
    '^': "..#../.#.#./#...#/...../...../...../.....",
    '_': "...../...../...../...../...../...../#####",
    '`': ".#.../..#../...../...../...../...../.....",
    'a': "...../...../.###./....#/.####/#...#/.####",
    'b': "#..../#..../####./#...#/#...#/#...#/####.",
    'c': "...../...../.####/#..../#..../#..../.####",
    'd': "....#/....#/.####/#...#/#...#/#...#/.####",
    'e': "...../...../.###./#...#/#####/#..../.###.",
    'f': "..##./.#..#/.#.../####./.#.../.#.../.#...",
    'g': "...../...../.####/#...#/.####/....#/.###.",
    'h': "#..../#..../####./#...#/#...#/#...#/#...#",
    'i': "..#../...../.##../..#../..#../..#../.###.",
    'j': "...#./...../..##./...#./...#./#..#./.##..",
    'k': "#..../#..../#..#./#.#../##.../#.#../#..#.",
    'l': ".##../..#../..#../..#../..#../..#../.###.",
    'm': "...../...../##.#./#.#.#/#.#.#/#...#/#...#",
    'n': "...../...../####./#...#/#...#/#...#/#...#",
    'o': "...../...../.###./#...#/#...#/#...#/.###.",
    'p': "...../...../####./#...#/####./#..../#....",
    'q': "...../...../.####/#...#/.####/....#/....#",
    'r': "...../...../#.##./##..#/#..../#..../#....",
    's': "...../...../.####/#..../.###./....#/####.",
    't': ".#.../.#.../####./.#.../.#.../.#..#/..##.",
    'u': "...../...../#...#/#...#/#...#/#..##/.##.#",
    'v': "...../...../#...#/#...#/#...#/.#.#./..#..",
    'w': "...../...../#...#/#...#/#.#.#/#.#.#/.#.#.",
    'x': "...../...../#...#/.#.#./..#../.#.#./#...#",
    'y': "...../...../#...#/#...#/.####/....#/.###.",
    'z': "...../...../#####/...#./..#../.#.../#####",
    '{': "...##/..#../..#../.#.../..#../..#../...##",
    '|': "..#../..#../..#../..#../..#../..#../..#..",
    '}': "##.../..#../..#../...#./..#../..#../##...",
    '~': "...../.#..#/#.#.#/#..#./...../...../.....",
}
UNKNOWN = "#####/#...#/#...#/#...#/#...#/#...#/#####"


def grey_png(width, height, lit, background, ink):
    #a greyscale png written by hand: a header, the rows each behind a filter byte, and an end. zlib and
    #struct are standard, which is the point - the container carries selenium and requests and nothing
    #else, and a page saying where its video went is not worth rebuilding an image over.
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows.extend(ink if (x, y) in lit else background for x in range(width))

    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body
                + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows), 9))
            + chunk(b'IEND', b''))


def stand_in(lines, width=1000, height=1400, background=28, ink=235):
    #the lines centred on a page of their own, as big as the longest of them allows. a long address is
    #never broken across lines, since a broken one cannot be read back, so the page widens for it rather
    #than shrinking the letters to where nobody can make out a video's id
    longest = max((len(line) for line in lines), default=1) or 1
    width = max(width, longest * 6 * 4 + 80)
    scale = max(2, min((width - 80) // (longest * 6), (height - 80) // (len(lines) * 10), 14))
    lit = set()
    wide, high = longest * 6 * scale, len(lines) * 10 * scale
    left0, top = (width - wide) // 2, (height - high) // 2
    for row, line in enumerate(lines):
        left = left0 + (wide - len(line) * 6 * scale) // 2
        for at, letter in enumerate(line):
            for y, dots in enumerate(GLYPHS.get(letter, UNKNOWN).split('/')):
                for x, dot in enumerate(dots):
                    if dot != '#':
                        continue
                    for dy in range(scale):
                        for dx in range(scale):
                            lit.add((left + (at * 6 + x) * scale + dx, top + (row * 10 + y) * scale + dy))
    return grey_png(width, height, lit, background, ink)


def archive_entry(folder, name):
    #what goes into the archive for this file: the file itself, or a stand-in page saying where the real
    #thing is. the original is never touched - the folder is the copy that keeps everything.
    lines = held_otherwise(folder, name)
    if not lines:
        return name, None
    return os.path.splitext(name)[0] + ".png", stand_in(lines)


def address_in(path):
    #the web address a note beside the pages holds, and whatever it calls it. wapsisquare's notes run the
    #two straight together - "Wapsi Square's The Library Ghost Story trailerhttps://youtube.com/..." -
    #so the address is looked for inside the line rather than as the whole of it.
    #
    #a comic's readme is not a page, though, and the difference is that a note about one page says almost
    #nothing else: it is short, and most of what it says is the address. a readme is longer than that,
    #whatever addresses it happens to mention.
    try:
        if os.path.getsize(path) > 1024:
            return None, None
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(1024).strip()
    except OSError:
        return None, None
    found = a_web_address.search(text)
    if not found:
        return None, None
    address = found.group(1).rstrip('.,;)')
    called = text[:found.start()].strip().strip('-:|').strip()
    return address, called or None


def held_otherwise(folder, name):
    #whether this file is a page of the comic kept in some form a reader cannot show, and what a stand-in
    #for it should say. the page is not lost - it is right there in the folder - so the stand-in's job is
    #to say so, and where.
    if video_types.search(name):
        return ["This page is a video.", "", "It is in the comic's folder as", name]
    if flash_types.search(name):
        return ["This page was Flash.", "", "It is in the comic's folder as", name]
    #a note about a page is named like a page - wapsisquare's are 4017.txt, beside 4016.png - which is
    #what tells it from a comic's readme. a readme can mention all the addresses it likes; it is still
    #not page 4017, and a ratio of address to prose could never have told the two apart reliably: one of
    #these notes is a long video title and one line of address.
    if link_types.search(name) and page_number(name) is not None:
        address, called = address_in(os.path.join(folder, name))
        if address:
            #the name the note gives it is worth showing: "Wapsi Square's The Library Ghost Story
            #trailer" says more about the page than the address does
            return (["This page is a video."] + (wrapped(called) if called else [])
                    + ["", address, "", "noted in the comic's folder as", name])
    return None


def wrapped(text, width=46):
    #prose broken into lines that fit. only ever used on what a note calls its page: an address is left
    #whole, because a broken one cannot be read back
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = "{0} {1}".format(line, word).strip()
    if line:
        lines.append(line)
    return [""] + lines if lines else []


def folder_pages(folder, others=False):
    #the comic's pages as files. a page held as a video, as flash, or as a note saying where it lives now
    #is asked for only where a page has to be accounted for - the lining up, and the packing that puts a
    #stand-in in its place
    names = [f for f in os.listdir(folder)
             if (page_types.search(f) or (others and held_otherwise(folder, f)))
             and os.path.isfile(os.path.join(folder, f))]
    #the order the comic reads in: by the number this script saved it under where there is one, and by
    #name otherwise. the number is the order pages were fetched, which is the order they were published.
    if names and all(page_number(name) is not None for name in names):
        return sorted(names, key=lambda name: (page_number(name), sort_key(name)))
    return sorted(names, key=sort_key)


def index_path(folder, root=None, args=None):
    #the comic's own folder decides the name, and nothing else: passing a library folder or not must never
    #change which cache a comic uses. the short tag is what keeps two comics called Extras apart.
    if args is not None and getattr(args, "cache", None):
        return args.cache
    full = os.path.abspath(folder)
    tag = hashlib.sha1(full.replace(os.sep, '/').lower().encode('utf-8')).hexdigest()[:8]
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(full)).strip('_') or "comic"
    here = os.path.join(config_folder(), "index", "{0}.{1}.jsonl".format(name, tag))
    if os.path.exists(here):
        return here
    #the same comic reached by another path - a share on one machine, a mount inside a container - hashes
    #differently, so the comic itself says which cache is its own and that is used when it is there
    named = ((read_metadata(folder).get("history") or {}).get("index_cache"))
    if named:
        elsewhere = os.path.join(config_folder(), "index", named)
        if os.path.exists(elsewhere):
            return elsewhere
    return here


def read_index(path):
    pages = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                pages.append(json.loads(line))
    return pages


def head_size(session, url):
    #a HEAD asks for the headers only, so this costs nothing but the round trip
    try:
        answer = session.head(url, timeout=20, allow_redirects=True)
        length = answer.headers.get("Content-Length")
        if length is None and answer.status_code < 400:
            #a site that will not answer a HEAD properly is asked for the first byte instead
            answer = session.get(url, timeout=20, stream=True, headers={"Range": "bytes=0-0"})
            length = (answer.headers.get("Content-Range") or "").rsplit("/", 1)[-1]
            answer.close()
        return int(length) if length and str(length).isdigit() else None
    except (requests.RequestException, ValueError):
        return None


def fill_sizes(path, pages, workers=6):
    #the size of an image is what identifies a page whose filename was changed years ago. asked once and
    #written back into the cache, so this only ever happens to pages that do not have it yet
    wanted = [page for page in pages if page.get("src") and page.get("bytes") is None]
    if not wanted:
        return 0
    print("Asking the site how big {0} image(s) are ...".format(len(wanted)))
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for page, size in zip(wanted, pool.map(lambda page: head_size(session, page["src"]), wanted)):
            page["bytes"] = size
            done += 1
            if done % 100 == 0:
                print("  {0} of {1}".format(done, len(wanted)))
    missed = [page["n"] for page in wanted if page.get("bytes") is None]
    if missed:
        print("  {0} image(s) would not say how big they are: {1}{2}".format(
            len(missed), missed[:6], "..." if len(missed) > 6 else ""))
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        for page in pages:
            f.write(json.dumps(page) + chr(10))
    os.replace(spare, path)
    return len(wanted) - len(missed)


def read_metadata(folder):
    try:
        with open(os.path.join(folder, metadata_file), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def recovered_files(folder, metadata=None):
    #pages the site itself no longer serves, which the reader found somewhere else and put in the folder
    #by hand. a walk cannot see them, so without being told, every tool here would call such a file a
    #stray and refuse to settle or to pack around it.
    metadata = read_metadata(folder) if metadata is None else metadata
    return {str(one.get("file")): one
            for one in ((metadata.get("history") or {}).get("recovered") or []) if one.get("file")}


def place_recovered(held, parcels, recovered):
    #a recovered page reads where it sits in the folder, which is where the reader put it: after the page
    #it follows. so it joins the chapter that page belongs to, rather than being appended somewhere tidy.
    known = {}
    for chapter, names in parcels:
        for name in names:
            known[name] = names
    placed = []
    for at, name in enumerate(held):
        if name not in recovered or name in known:
            continue
        before = next((held[back] for back in range(at - 1, -1, -1) if held[back] in known), None)
        names = known[before] if before else (parcels[0][1] if parcels else None)
        if names is None:
            continue
        names.insert(names.index(before) + 1 if before else 0, name)
        known[name] = names
        placed.append(name)
    return placed


def longest_run(pairs):
    #anchors have to agree with each other: keep the longest set that runs forwards through both lists
    #and drop the rest, rather than trusting a name that happens to appear twice
    best = []
    for at, pair in enumerate(pairs):
        run = max((best[before] for before in range(at)
                   if pairs[before][0] < pair[0] and pairs[before][1] < pair[1]), key=len, default=[])
        best.append(run + [pair])
    return max(best, key=len, default=[])


def unique_pairs(by_page, by_file):
    #only what points at exactly one thing on each side: anything ambiguous is no use as an anchor
    pairs = []
    for value, wheres in by_page.items():
        heres = by_file.get(value)
        if len(wheres) == 1 and heres and len(heres) == 1:
            pairs.append((wheres[0], heres[0]))
    return pairs


def align(pages, files, folder=None):
    #pages are what the walk saw, in order; files are what is on disk, in order. the answer is which file
    #each page was saved as. anchors - pages whose image name is still recognisable in a filename - pin
    #positions exactly; between two anchors, a stretch that holds the same number of each lines up one to
    #one. a stretch where the counts differ is left unaligned and reported rather than guessed at.
    #by name: the page whose image is still recognisable in a filename
    name_pages, name_files = {}, {}
    for at, page in enumerate(pages):
        if page.get("file"):
            name_pages.setdefault(page_key(page["file"]), []).append(at)
    for at, name in enumerate(files):
        name_files.setdefault(page_key(name), []).append(at)

    #by size: what identifies a page whose file was renamed. the bytes on disk are the bytes the site
    #sent, so an exact match on a size nothing else shares is as good as a name
    size_pages, size_files = {}, {}
    if folder:
        for at, page in enumerate(pages):
            if page.get("bytes"):
                size_pages.setdefault(page["bytes"], []).append(at)
        for at, name in enumerate(files):
            try:
                size_files.setdefault(os.path.getsize(os.path.join(folder, name)), []).append(at)
            except OSError:
                pass

    found, why = {}, {}
    for at, to in unique_pairs(size_pages, size_files):
        found[at], why[at] = to, "size"
    #a name that agrees is no extra information, and a name that disagrees is the weaker of the two
    for at, to in unique_pairs(name_pages, name_files):
        if at not in found:
            found[at], why[at] = to, "name"
    anchors = longest_run(sorted(found.items()))

    aligned = [None] * len(pages)
    how = [None] * len(pages)
    for at, to in anchors:
        aligned[at], how[at] = files[to], why[at]

    trouble = []
    edges = [(-1, -1)] + anchors + [(len(pages), len(files))]
    for (page_from, file_from), (page_to, file_to) in zip(edges, edges[1:]):
        pages_between = page_to - page_from - 1
        files_between = file_to - file_from - 1
        if pages_between <= 0 and files_between <= 0:
            continue
        where = "pages {0}-{1}".format(page_from + 2, page_to) if pages_between else "after page {0}".format(page_to)
        if files_between == 0:
            #the comic has these and this folder does not, which is a gap to fill, not a puzzle to solve
            continue
        if pages_between == files_between:
            for step in range(pages_between):
                aligned[page_from + 1 + step] = files[file_from + 1 + step]
                how[page_from + 1 + step] = "order"
        else:
            trouble.append({
                "where": where,
                "pages": pages_between,
                "files": files_between,
                "detail": "{0} page(s) walked but {1} file(s) held".format(pages_between, files_between),
            })
    return aligned, how, anchors, trouble


def anchor_kinds(pages, files, anchors, folder):
    #how each anchor was recognised, for the report: by its name, or by its size
    kinds = {"name": 0, "size": 0}
    for at, to in anchors:
        same_name = pages[at].get("file") and page_key(pages[at]["file"]) == page_key(files[to])
        kinds["name" if same_name else "size"] += 1
    return kinds


def verify(folder, files, pages, aligned):
    #every placement can be checked, not just the anchored ones: the file on disk should be as big as the
    #site says its image is. a size that differs is not proof of anything on its own - a comic that moved
    #host years ago serves re-encoded images that no longer match what was downloaded then. what does
    #prove something is the site's size matching a DIFFERENT file in this folder: that is a page sitting
    #where another page's file is, which is exactly what a wrong alignment looks like.
    held_sizes = {}
    for name in files:
        try:
            held_sizes.setdefault(os.path.getsize(os.path.join(folder, name)), []).append(name)
        except OSError:
            pass
    agree, changed, conflict = 0, 0, []
    for page, name in zip(pages, aligned):
        if not name or not page.get("bytes"):
            continue
        held = held_sizes and next((size for size, names in held_sizes.items() if name in names), None)
        if held == page["bytes"]:
            agree += 1
        elif page["bytes"] in held_sizes:
            conflict.append((page["n"], name, held_sizes[page["bytes"]][:2]))
        else:
            changed += 1
    return agree, changed, conflict


def describe(folder, pages, files, aligned, how, anchors, trouble, rescued=(), recovered=None):
    matched = [name for name in aligned if name]
    recovered = recovered or {}
    spare = [name for name in files if name not in set(matched)]
    print("{0}".format(folder))
    ways = ", ".join("{0} by {1}".format(how.count(way), way) for way in ("size", "name", "order", "time")
                     if how.count(way))
    print("  {0} pages walked, {1} files held, {2} lined up ({3})".format(
        len(pages), len(files), len(matched), ways or "none"))
    if anchors:
        kinds = anchor_kinds(pages, files, anchors, folder)
        first, last = anchors[0], anchors[-1]
        print("  {0} anchor(s) agree ({1} by name, {2} by size), from page {3} ({4}) to page {5} ({6})".format(
            len(anchors), kinds["name"], kinds["size"], first[0] + 1, files[first[1]],
            last[0] + 1, files[last[1]]))
    elif "time" in how:
        print("  lined up by when each file was written, so the sizes below are the whole check")
    else:
        print("  no filename anchors: every page was renamed, so this rests on the counts matching")
    missing = [page for page, name in zip(pages, aligned) if not name]
    if missing:
        print("  {0} page(s) the comic has and this folder does not:".format(len(missing)))
        for page in missing[:12]:
            print("      page {0:<5} {1}".format(page["n"], page["url"]))
        if len(missing) > 12:
            print("      ... and {0} more".format(len(missing) - 12))
    if rescued:
        print("  {0} page(s) here that the site no longer serves, put back by hand:".format(len(rescued)))
        for name in rescued[:6]:
            print("      {0:<34} {1}".format(name[:34], (recovered[name].get("note") or "")[:52]))
        if len(rescued) > 6:
            print("      ... and {0} more".format(len(rescued) - 6))
    if spare:
        print("  {0} file(s) no page claims: {1}{2}".format(
            len(spare), spare[:4], "..." if len(spare) > 4 else ""))
        print("      a page the site has lost, that you found elsewhere, is not a stray: say so with "
              "chapters.py recovered {0} --file <name>".format(folder))
    #a page held as a video never matches the name of the image the site draws it with, and saying so
    #once is worth more than listing every one of them as a file that is not what the walk saw
    filmed = [name for name in aligned if name and video_types.search(name)]
    if filmed:
        print("  {0} page(s) are held as video rather than as a picture: {1}{2}".format(
            len(filmed), filmed[:4], "..." if len(filmed) > 4 else ""))
    named = [(page, name) for page, name in zip(pages, aligned)
             if name and page.get("src") and not video_types.search(name)]
    astray = [(page, name) for page, name in named
              if page_key(os.path.basename(page["src"].split('?')[0])) != page_key(name)]
    #only worth saying when most files ARE named after their image: then the few that are not stand out
    #as a page whose saved file is not its image - a scrape that caught a banner or an icon instead. on a
    #comic the site renamed wholesale, nothing matches and this says nothing.
    if named and len(astray) <= len(named) / 2:
        if astray:
            print("  {0} file(s) here are not the image the walk saw on that page:".format(len(astray)))
            for page, name in astray[:6]:
                print("      page {0:<5} {1:<26} site serves {2}".format(
                    page["n"], name[:26], os.path.basename(page["src"].split('?')[0])))
            if len(astray) > 6:
                print("      ... and {0} more".format(len(astray) - 6))
            print("      chapters.py refetch {0} --page <n> --as-named puts one right.".format(folder))
    agree, changed, conflict = verify(folder, files, pages, aligned)
    #a size says where a page is only where sizes say anything at all. a site that re-exported its whole
    #archive - avasdemon.com did, at four fifths the size - leaves every one of them different, and then
    #a size that happens to match some other file among thousands is a coincidence rather than a page in
    #the wrong place. so they are still reported, and they stop counting as a fault.
    sizes_tell = agree >= changed
    print("  checked against the site's own sizes: {0} match exactly, {1} differ (re-uploaded since, "
          "and their size is held by no other file here), {2} land on another page's file".format(
              agree, changed, len(conflict)))
    for n, name, others in conflict[:8]:
        print("      page {0:<5} placed at {1:<26} but its size belongs to {2}".format(n, name[:26], others))
    if len(conflict) > 8:
        print("      ... and {0} more".format(len(conflict) - 8))
    if conflict and not sizes_tell:
        print("      only {0} of {1} sizes match the site at all, so these are coincidences among "
              "thousands of files rather than pages out of place.".format(agree, agree + changed))
    for problem in trouble:
        print("  UNRESOLVED {0}: {1}".format(problem["where"], problem["detail"]))
    #what chaptering needs is that every file is placed. a page the comic has and this folder does not
    #leaves a gap in the reading, but the files either side of it are still placed correctly.
    settled = not trouble and not spare and not (conflict and sizes_tell)
    if settled and missing:
        print("  settled: every file is placed. The {0} page(s) above are missing from this folder, "
              "not misplaced.".format(len(missing)))
    elif settled:
        print("  settled: every page has a file and every file has a page")
    else:
        print("  NOT settled: fix the above, or align by hand, before chaptering")
    return settled


def remember_cache(folder, path):
    #written into the comic so another machine, where this folder has a different path, still finds it
    metadata = read_metadata(folder)
    if not metadata:
        return
    history = metadata.setdefault("history", {})
    if history.get("index_cache") != os.path.basename(path):
        history["index_cache"] = os.path.basename(path)
        write_metadata(folder, metadata)


def save_alignment(path, folder, pages, aligned, how, settled):
    out = {
        "comic": folder,
        "settled": settled,
        "pages": [{"n": page["n"], "url": page["url"], "title": page.get("title"),
                   "src": page.get("src"), "file": name, "how": way}
                  for page, name, way in zip(pages, aligned, how)],
    }
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1)
        f.write(chr(10))
    os.replace(spare, path)
    return path


def write_metadata(folder, metadata):
    path = os.path.join(folder, metadata_file)
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
        f.write(chr(10))
    os.replace(spare, path)


def gap_notes(pages, aligned):
    #what the comic has that this folder does not, and pages the site shows with no image at all - a flash
    #page, usually. written into the metadata so the next person to look does not have to work it out
    #again, and so a page saved by hand is not mistaken for a mistake later.
    gaps, oddities = [], []
    for page, name in zip(pages, aligned):
        imageless = not page.get("src")
        if not name:
            gaps.append({
                "page": page["n"], "url": page["url"], "title": page.get("title"),
                "note": "the site shows no image on this page, which is usually flash; nothing saved"
                        if imageless else "no file here for this page",
            })
        elif imageless:
            oddities.append({
                "page": page["n"], "url": page["url"], "file": name,
                "note": "the site shows no image on this page, so this file was made by hand",
            })
    return gaps, oddities


def save_gaps(folder, pages, aligned):
    metadata = read_metadata(folder)
    if not metadata:
        print("  no metadata here, so the gaps were not written down")
        return 0
    gaps, oddities = gap_notes(pages, aligned)
    history = metadata.setdefault("history", {})
    #kept even when empty, so "this comic has been looked at and has no gaps" is a thing the file can say
    history["gaps"] = gaps
    if oddities:
        history["hand_made"] = oddities
    elif "hand_made" in history:
        del history["hand_made"]
    history["gaps_checked"] = time_stamp()
    write_metadata(folder, metadata)
    print("  wrote {0} gap(s) and {1} hand-made page(s) into {2}".format(
        len(gaps), len(oddities), os.path.join(folder, metadata_file)))
    return len(gaps)


def time_stamp():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- where the chapters are ----------------
def same_page(url):
    #one page can be written several ways - http or https, with or without www or a trailing slash - so
    #everything is reduced to the part that actually identifies it before anything is compared
    url = (url or "").strip()
    url = re.sub(r'^https?://', '', url, flags=re.I)
    url = re.sub(r'^www\.', '', url, flags=re.I)
    return url.rstrip('/').lower()


def drawn_heading(attrs):
    #a site that draws its chapter headings instead of writing them. avasdemon.com heads each chapter with
    #<img src="chapter12.png"> and no words at all, so the only name on the page is in the picture - and
    #the picture's own filename is where the number is. the alt is preferred when there is one, since that
    #is the site saying what the picture means.
    text = (attrs.get("alt") or "").strip()
    if not text:
        name = (attrs.get("src") or "").rsplit('/', 1)[-1].partition('?')[0]
        text = re.sub(r'\s+', ' ', re.sub(r'[_-]+', ' ', re.sub(r'\.\w+$', '', name))).strip()
    #the word has to be followed by its number or by nothing, or "partners" and "bookmark" would head
    #chapters of their own
    if not re.match(r'^(chapters?|chap|arcs?|volumes?|vol|books?|parts?|episodes?|seasons?)'
                    r'\s*[-_.]?\s*(\d|$)', text, re.I):
        return None
    #"chapter12" is a name with its number run into it, which reads better - and sorts better - apart
    text = re.sub(r'^([^\W\d_]+)(\d)', r'\1 \2', text)
    return text[:1].upper() + text[1:]


class ArchiveReader(html.parser.HTMLParser):
    #reads a comic's archive page as a sequence of two things: headings, and links. what a heading looks
    #like differs from site to site - a real heading tag on one, a bold line or a table cell on another -
    #so anything that could be one is kept, and a link is later put under whichever came last before it.
    #a table header is a real heading for the rows under it: an archive built as one table per chapter,
    #with the chapter's name in its th, says where chapters start as plainly as any h2 does
    heading_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "th", "b", "strong", "legend", "caption", "summary")
    title_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "th")

    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.events = []
        self.heading = None
        self.rank = 1
        self.said = []
        #what the heading says in its own right, with the words of the links inside it left out. a real
        #heading is usually one or the other, and telling them apart is what saves a container full of
        #links from reading as a heading whose name is every link in it, run together
        self.said_alone = []
        self.inside = []
        self.link = None
        self.link_text = []

    def handle_starttag(self, tag, attrs):
        got = dict(attrs)
        if tag == "a" and got.get("href"):
            self.link = got["href"]
            self.link_text = []
            return
        #some archives are a dropdown rather than a list of links: snafu-comics lists every page of a
        #comic as an <option>, and its script sends you to the value when you pick one. that is a link
        #by any other name, and without reading it such a page says nothing at all.
        if tag == "option" and got.get("value"):
            self.link = got["value"]
            self.link_text = []
            return
        if tag == "img" and self.heading not in self.title_tags:
            #a drawn heading, which stands on its own. inside a written heading the picture is part of what
            #that heading says and is left to it - but a container named "chapters", which is what wraps
            #the whole list on a page like this, is not a heading that can say anything
            drawn = drawn_heading(got)
            if drawn:
                #ranked below a written heading, so a site that has both is named by its words
                self.events.append(("heading", drawn, 1))
            return
        #whole words only: a class called comic-archive-date holds "arc" inside "archive" and is a date,
        #not a heading
        words = set(re.split(r'[^a-z]+', "{0} {1}".format(got.get("class") or "", got.get("id") or "").lower()))
        looks_like = tag in self.heading_tags or bool(
            words & {"chapter", "chapters", "arc", "arcs", "volume", "book", "story", "storyline"})
        #the outermost heading wins, so a <b> inside an <h4> is emphasis in a title rather than a title of
        #its own - except that a real heading tag beats a container whose class merely says "chapter",
        #since such a container holds the description and the icon too, and none of that is a name
        if looks_like and (not self.heading
                           or (tag in self.title_tags and self.heading not in self.title_tags)):
            if not self.heading:
                self.inside = []
            self.heading = tag
            self.rank = 0 if tag in self.title_tags else 1
            self.said = []

    def words_of_its_own(self):
        #whether this candidate says anything beyond the links it holds. the separators between links are
        #not words, and neither is the whitespace laying them out
        return bool(re.search(r'[^\W_]', "".join(self.said_alone)))

    def stop_holding(self):
        #this candidate is holding a list of links rather than naming something, so it is a container and
        #not a heading: avasdemon.com wraps its whole chapter list in <div id="chapters"> and gives each
        #chapter's table an id of chapter12_table, and both read as headings by their names alone. given
        #up as soon as it is plain, so everything after it - drawn headings included - is read where it
        #stands rather than being held back and handed out at the closing tag, out of order.
        said = re.sub(r'\s+', ' ', "".join(self.said_alone)).strip()
        if re.search(r'[^\W_]', said):
            #whatever words it has of its own can still name what follows; the bars between its links cannot
            self.events.append(("heading", said, self.rank))
        for href, text in self.inside:
            self.events.append(("link", href, text))
        self.heading = None
        self.said = []
        self.said_alone = []
        self.inside = []

    def handle_endtag(self, tag):
        if tag in ("a", "option") and self.link is not None:
            said = re.sub(r'\s+', ' ', "".join(self.link_text)).strip()
            if self.heading:
                #some archives put the chapter's link inside the heading that names it, rather than under
                #it. held back and given out after the heading, so it still reads as "this heading, then
                #the page it starts at" - which is what every other archive says plainly.
                self.inside.append((self.link, said))
                self.link = None
                self.link_text = []
                #one link inside a name is a heading pointing at its own chapter. more than one, with
                #nothing said around them, is a list of pages: a table of links and the bars between them
                #says "0008|0009|" for itself, which is not a name however much it looks like text. a
                #third link settles it either way, since no heading is built out of three links.
                if len(self.inside) > 2 or (len(self.inside) > 1 and not self.words_of_its_own()):
                    self.stop_holding()
                return
            self.events.append(("link", self.link, said))
            self.link = None
            self.link_text = []
            return
        if self.heading and tag == self.heading:
            said = re.sub(r'\s+', ' ', "".join(self.said)).strip()
            if not re.search(r'[^\W_]', said):
                #punctuation and the separators between links are not a name
                said = ""
            if said:
                self.events.append(("heading", said, self.rank))
            for href, text in self.inside:
                #a heading that holds the link names that chapter and nothing else does, whatever else
                #sits above it on the page. the heading is still given out on its own as well, so if this
                #link turns out not to be a page of the comic it can still name the next one that is.
                self.events.append(("owned", href, said) if said else ("link", href, text))
            self.heading = None
            self.said = []
            self.said_alone = []
            self.inside = []

    def handle_data(self, data):
        #a link inside a heading is part of what the heading says, as well as being the link
        if self.link is not None:
            self.link_text.append(data)
        if self.heading:
            self.said.append(data)
            if self.link is None:
                self.said_alone.append(data)


def read_archive(url, browser=False, script=None):
    if browser:
        #for an archive a plain fetch comes back empty on, because the page builds itself with javascript
        done = subprocess.run([sys.executable, script or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "mirror_base.py"), "--page-source", url],
            capture_output=True, text=True, timeout=300)
        return done.stdout
    answer = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    answer.raise_for_status()
    return answer.text


def heading_says(text):
    #an archive that says how long each chapter is: "3. Merry Snow Day (4 pages, 5/8/06)". the count is
    #the site's own word on how many pages the chapter holds, which is something a reading can be checked
    #against, and it is not part of the chapter's name.
    found = re.search(r'\(\s*(\d+)\s*pages?\b[^)]*\)\s*$', text or "", re.I)
    if not found:
        return (text or "").strip(), None
    return text[:found.start()].strip().strip(',;:-').strip(), int(found.group(1))


def says_it_twice(url):
    #a path with the same step twice in a row, which is what a mis-joined relative link looks like
    steps = same_page(url or "").partition('?')[0].split('/')
    return 1 if any(one and one == next_one for one, next_one in zip(steps, steps[1:])) else 0


def link_targets(base, href):
    #where a link points, allowing for the two ways an archive writes one. a dropdown's value is what its
    #script navigates to, and such values are usually written from the site's root rather than from the
    #page's own folder - snafu-comics writes "powerpuffgirls/first-day" on a page that already sits in
    #/powerpuffgirls/. both readings are offered and whichever is a page of the comic is the one meant.
    here = urljoin(base, href)
    from_root = urljoin(urljoin(base, '/'), href.lstrip('/'))
    if here == from_root:
        return [here]
    #joining "powerpuffgirls/first-day" onto a page already inside /powerpuffgirls/ says it twice, and no
    #site has a path like that. so a reading that repeats a step is tried last, not first.
    return sorted([here, from_root], key=says_it_twice)


def pages_linked(events, base, known):
    #the comic's own pages linked on an archive page, in the order that page lists them, each counted
    #once. everything else linked there - the shop, the artist's other comics, the archive itself - is
    #not a page of this comic and is left out.
    links, order = [], {}
    for kind, first, second in events:
        if kind not in ("link", "owned"):
            continue
        where = next((one for one in link_targets(base, first) if looks_like_pages(one, known)), None)
        if where is None or same_page(where) in order:
            continue
        links.append(where)
        order[same_page(where)] = len(order) + 1
    return links, order


def chapters_from_events(events, where, base=""):
    #a chapter starts at the first page link after a heading. several headings can sit together - a title
    #and the summary underneath it - so the one that reads most like a title wins: a real heading tag
    #first, and the earliest of those.
    found, waiting, listed = [], [], 0
    for kind, first, second in events:
        if kind == "heading":
            waiting.append((second if second is not None else 1, len(waiting), first))
            continue
        owned = kind == "owned"
        at = next((where[same_page(one)] for one in link_targets(base, first)
                   if same_page(one) in where), None)
        if at is None:
            continue
        listed += 1
        already = next((chapter for chapter in found if chapter["start_page"] == at), None)
        if owned and already is not None:
            #this page already starts a chapter, named by whatever mentioned it first - often a dropdown
            #of every page under the archive's own banner. a heading built round this very link knows
            #better, so it renames that chapter rather than making a second one at the same page.
            already["label"], already["pages_said"] = heading_says(second)
            continue
        if owned or waiting or not found:
            #a heading that held this very link names it outright. otherwise the most heading-like wins,
            #and among equals the one nearest the link: a page's own banner sits far above the first
            #chapter's title, and a summary sits just under it
            label = (second if owned else
                     min(waiting, key=lambda held: (held[0], -held[1]))[2] if waiting
                     else "Chapter {0}".format(len(found) + 1))
            label, says = heading_says(label)
            found.append({"label": label or "Chapter {0}".format(len(found) + 1),
                          "start_page": at, "pages_listed": [], "pages_said": says})
            waiting = []
        found[-1]["pages_listed"].append(at)
        found[-1]["start_page"] = min(found[-1]["start_page"], at)
    return found, listed


def chapters_from_archive(url, pages, browser=False, script=None):
    #the archive page says where each chapter starts; the walk says where every page sits. matching one
    #against the other needs no knowledge of the site beyond which links are pages of this comic.
    where = {same_page(page["url"]): page["n"] for page in pages}
    reader = ArchiveReader()
    reader.feed(read_archive(url, browser, script))
    #plenty of archives link their pages relatively, so each is read against the archive's own address
    return chapters_from_events(reader.events, where, url)


def numbers_in(url):
    #every number in the address, with the text that comes before it, so a chapter can be recognised
    #whether it is a path of its own (/c4/p7) or part of a name (/comic/issue-4-page-7)
    return [(bit.start(), int(bit.group())) for bit in re.finditer(r'\d+', same_page(url))]


def chapter_word(key):
    #a name for a chapter, out of the piece of the address that names it: issue-4 is Issue 4, c4 is
    #Chapter 4, and a bare 4 is Chapter 4 as well
    #keys are written as "the path/word#number", which is how a chapter is named and counted
    tail = key.rstrip('/').rsplit('/', 1)[-1].replace('#', ' ')
    found = re.match(r'^(.*?)[-_ ]?(\d+)$', tail.strip())
    if not found:
        return tail.replace('-', ' ').strip().title() or "Chapter"
    word = re.sub(r'[-_]+', ' ', found.group(1)).strip().lower()
    known = {"": "Chapter", "c": "Chapter", "ch": "Chapter", "chap": "Chapter", "chapter": "Chapter",
             "i": "Issue", "iss": "Issue", "issue": "Issue", "v": "Volume", "vol": "Volume",
             "volume": "Volume", "b": "Book", "book": "Book", "part": "Part", "arc": "Arc",
             "p": "Chapter", "page": "Chapter", "strip": "Chapter"}
    if word not in known and len(word) <= 3:
        #a short tag before the number is a site's shorthand for the comic itself - /ss/12-1 is Swords and
        #Sausages chapter 12 - and naming the chapter after the comic says nothing
        word = ""
    return "{0} {1}".format(known.get(word, word.title() or "Chapter"), int(found.group(2)))


def group_by_url(pages, at):
    #group pages by everything up to and including the (at+1)th number in the address. a page with no such
    #number - a cover, a feed link - stays in the chapter it follows.
    keys, numbers = [], []
    for page in pages:
        found = numbers_in(page["url"])
        if len(found) > at:
            where, value = found[at]
            #the words before the number, tidied: a site that writes issue-20 on one page and issues-20 on
            #the next means the same chapter, and a stray plural must not split it in two
            before = re.sub(r'[^a-z0-9]+', ' ', same_page(page["url"])[:where].lower()).strip()
            word = before.split(' ')[-1] if before else ''
            keys.append("{0}/{1}#{2}".format(before[:before.rfind(' ')] if ' ' in before else '',
                                             word[:-1] if word.endswith('s') and len(word) > 2 else word,
                                             value))
            numbers.append(value)
        else:
            keys.append(keys[-1] if keys else None)
            numbers.append(numbers[-1] if numbers else None)
    return keys, numbers


def read_in_order(pages, keys, numbers):
    #a chapter starts where the number goes up, and everything after it belongs to that chapter until the
    #next one does. a stray page whose address says something else - a one-off slug, a cover named oddly -
    #stays where it was published rather than becoming a chapter of its own.
    chapters = []
    for page, key, number in zip(pages, keys, numbers):
        if number is not None and (not chapters or number > chapters[-1]["number"]):
            chapters.append({"number": number, "start_page": page["n"], "keys": [], "pages_listed": []})
        if not chapters:
            continue
        if key is not None:
            chapters[-1]["keys"].append(key)
        chapters[-1]["pages_listed"].append(page["n"])
    return chapters


def agreement(chapters):
    #how much of each chapter's pages say the same thing: a grouping where most pages disagree with the
    #chapter they are in is not a grouping, it is a coincidence
    agreed = held = 0
    for chapter in chapters:
        if not chapter["keys"]:
            continue
        common = collections.Counter(chapter["keys"]).most_common(1)[0]
        chapter["label"] = chapter_word(common[0])
        agreed += common[1]
        held += len(chapter["keys"])
    return agreed / held if held else 0


def chapters_from_urls(pages):
    #a comic whose addresses carry the chapter: /c4/p7, /ss/4-7, /comic/issue-4-page-7. every number in
    #the address is tried as the chapter, and whichever reads best wins.
    if len(pages) < 4:
        return []
    most = max((len(numbers_in(page["url"])) for page in pages), default=0)
    best = None
    for at in range(most):
        keys, numbers = group_by_url(pages, at)
        #a comic cannot hold more chapters than it holds pages, so a number bigger than that is not one:
        #a date written 20211202, a year, an id. left in, it jumps so far ahead that nothing after it can
        #start a chapter, and the whole rest of the comic falls into it.
        keys = [key if number is not None and number <= len(pages) else None
                for key, number in zip(keys, numbers)]
        numbers = [number if key else None for key, number in zip(keys, numbers)]
        counted = [number for number in numbers if number is not None]
        if not counted or counted[0] not in (0, 1):
            #a chapter is counted from where a comic starts counting. a date is not.
            continue
        #pages whose address does not follow the shape most of them use - a one-off slug, a link to
        #something else entirely - are not chapters starting, they are pages inside the chapter they sit
        #in. left alone, one of them jumping ahead in the numbers swallows everything after it.
        shapes = collections.Counter(key.split('#')[0] for key in keys if key)
        usual = shapes.most_common(1)[0][0] if shapes else None
        keys = [key if key and key.split('#')[0] == usual else None for key in keys]
        numbers = [number if key else None for key, number in zip(keys, numbers)]
        counted = [number for number in numbers if number is not None]
        if not counted or counted[0] not in (0, 1):
            continue
        chapters = read_in_order(pages, keys, numbers)
        if not (2 <= len(chapters) <= max(2, len(pages) // 2)):
            continue
        agreed = agreement(chapters)
        if agreed < 0.8:
            continue
        steps = [chapter["number"] for chapter in chapters]
        tidy = 1 if all(b - a == 1 for a, b in zip(steps, steps[1:])) else 0
        named = 1 if re.search(r'(issue|chapter|chap|book|volume|vol|part|arc)',
                               chapters[0].get("label", ''), re.I) else 0
        score = (named, tidy, round(agreed, 2), -len(chapters))
        if best is None or score > best[0]:
            best = (score, chapters)
    if best is None:
        return []
    for chapter in best[1]:
        chapter.pop("keys", None)
        chapter.pop("number", None)
    return best[1]


def chapters_from_list(path, pages):
    #a list of addresses, one for each chapter start, with an optional title after it
    where = {same_page(page["url"]): page["n"] for page in pages}
    found, unknown = [], []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            url, _, label = line.partition('|') if '|' in line else (line.split()[0], None, ' '.join(line.split()[1:]))
            at = where.get(same_page(url.strip()))
            if at is None:
                unknown.append(url)
                continue
            found.append({"label": label.strip() or "Chapter {0}".format(len(found) + 1),
                          "start_page": at, "pages_listed": [at]})
    for url in unknown:
        print("  no page of this comic is at {0}".format(url))
    return found


def settle_chapters(found, pages, shift=0):
    #chapters are read in the order the comic is read, and each one runs until the next one starts, so
    #anything between them - filler, guest art, a flash page with no file - stays where it was published
    for chapter in found:
        chapter["start_page"] = max(1, min(len(pages), chapter["start_page"] + shift))
    found = sorted(found, key=lambda chapter: chapter["start_page"])
    settled, seen = [], set()
    for chapter in found:
        if chapter["start_page"] in seen:
            continue #two headings pointing at one page is one chapter
        seen.add(chapter["start_page"])
        settled.append(chapter)
    by_page = {page["n"]: page for page in pages}
    for at, chapter in enumerate(settled):
        ends = settled[at + 1]["start_page"] - 1 if at + 1 < len(settled) else pages[-1]["n"]
        chapter["number"] = at + 1
        chapter["end_page"] = ends
        chapter["pages"] = ends - chapter["start_page"] + 1
        start = by_page.get(chapter["start_page"], {})
        chapter["start_url"] = start.get("url")
        chapter["start_file"] = start.get("file")
        chapter.pop("pages_listed", None)
    return settled


def page_at(pages, where):
    #which page an address is. a fix names its page this way because an address does not change when
    #pages are added before it, while a page number does
    want = same_page(str(where or ""))
    for page in pages:
        if same_page(page["url"]) == want:
            return page["n"]
    return None


def apply_fixes(found, pages, fixes):
    #corrections made by hand, kept apart from whatever rule worked the chapters out so that reading the
    #archive again, or the addresses again, never throws them away. each one says either that a chapter
    #starts at a page, or that one does not - which covers a boundary in the wrong place, a chapter the
    #site named oddly, and a heading that was never a chapter at all.
    took, missed = [], []
    for fix in fixes or []:
        at = page_at(pages, fix.get("url")) if fix.get("url") else fix.get("page")
        if not at or at > len(pages):
            missed.append(fix.get("url") or fix.get("page"))
            continue
        found = [chapter for chapter in found if chapter["start_page"] != at]
        if not fix.get("drop"):
            label = fix.get("label") or "Chapter"
            #naming a chapter that is already there moves it here rather than making a second one of the
            #same name: a cover the artist named oddly is the same chapter, starting a page earlier. that
            #holds for one this rule found and for one an earlier correction put somewhere else.
            found = [chapter for chapter in found if (chapter.get("label") or "") != label]
            found.append({"label": label, "start_page": at, "by_hand": True})
        took.append((at, None if fix.get("drop") else fix.get("label")))
    return found, took, missed


def say_fixes(took, missed):
    for at, label in took:
        print("  by hand: {0}".format("no chapter starts at page {0}".format(at) if label is None
                                      else "page {0} starts {1}".format(at, label)))
    for where in missed:
        print("  by hand: {0} is not a page of this comic, so that correction did nothing".format(where))


def show_chapters(folder, chapters, pages, listed=None):
    print("{0}: {1} chapter(s) over {2} page(s)".format(folder, len(chapters), len(pages)))
    if listed is not None:
        print("  the archive listed {0} of this comic's {1} pages".format(listed, len(pages)))
    before = chapters[0]["start_page"] - 1 if chapters else 0
    if before:
        print("  {0} page(s) come before the first chapter starts".format(before))
    print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}".format("no", "label", "from", "to", "pages", "starts at"))
    for chapter in chapters:
        print("  {0:<4} {1:<44} {2:>7} {3:>7} {4:>7}  {5}{6}".format(
            chapter["number"], (chapter["label"] or "")[:44], chapter["start_page"], chapter["end_page"],
            chapter["pages"], (chapter["start_file"] or "?"),
            "  <- by hand" if chapter.get("by_hand") else ""))
    odd = [c for c in chapters if c["pages"] <= 1]
    if odd:
        print("  {0} chapter(s) hold one page or none, which usually means a heading was read wrongly: "
              "{1}".format(len(odd), [c["number"] for c in odd[:8]]))


def chapter_record(chapter):
    kept = {"number": chapter["number"], "label": chapter["label"], "start_page": chapter["start_page"],
            "end_page": chapter["end_page"], "pages": chapter["pages"], "start_url": chapter["start_url"],
            "start_file": chapter["start_file"]}
    if chapter.get("by_hand"):
        kept["by_hand"] = True
    return kept


def save_chapters(folder, chapters, source, source_url=None):
    metadata = read_metadata(folder)
    if not metadata:
        print("  no metadata here, so the chapters were not saved")
        return 1
    was = metadata.get("chapters") or {}
    metadata["chapters"] = {
        "source": source,
        "source_url": source_url,
        "checked": time_stamp(),
        "list": [chapter_record(c) for c in chapters],
    }
    #a correction is about this comic, not about one run of one rule, and where the archives are and when
    #they were written describes what is on disk, not this reading. neither is the reading's to throw away
    for kept in ("fixes", "packed", "folder"):
        if was.get(kept):
            metadata["chapters"][kept] = was[kept]
    write_metadata(folder, metadata)
    print("  saved {0} chapter(s) into {1}".format(len(chapters), os.path.join(folder, metadata_file)))
    return 0


def compare_chapters(was, now):
    #what changed, in the terms that matter: a chapter added at the end is safe to take, while one that
    #moved or vanished means pages would leave archives that already hold them
    was = was or []
    older = [(c["start_page"], c.get("label")) for c in was]
    newer = [(c["start_page"], c.get("label")) for c in now]
    if older == newer[:len(older)]:
        return "same" if len(newer) == len(older) else "longer", newer[len(older):]
    moved = [old for old, fresh in zip(older, newer) if old != fresh]
    return "changed", moved


def looks_like_pages(url, known):
    #without an index nothing knows this comic's addresses, so a link counts as a page when it sits on the
    #same site and under the same part of the path as the page the comic is known to be on
    def parts(where):
        site, _, rest = same_page(where or "").partition('/')
        path = rest.partition('?')[0]
        return site, (path.split('/')[0] if path else '')

    site, first = parts(known)
    where, theirs = parts(url)
    if not site or where != site:
        return False
    #the same first step of the path: /comic/... for one comic, index.php?pid=... for another. a link to
    #the archive itself, or to some other page of the site, is not a page of the comic.
    if theirs == first:
        return True
    #or the same shape, for a comic that puts the chapter in the first step and so has no fixed one:
    #/c1/p1, /c2/p1, /c12.1/p1 are all the same kind of address, and archive.html is not.
    return bool(re.match(page_shape(known), same_page(url).partition('?')[0]))


def page_shape(known):
    #the address with every run of digits (and the dots inside them) made a wildcard, so one page of a
    #comic describes the rest: c1/p1 becomes c<number>/p<number>
    plain = same_page(known or "").partition('?')[0]
    return "".join("[0-9.]+" if bit[0].isdigit() else re.escape(bit)
                   for bit in re.findall(r'\d[\d.]*|\D+', plain)) + "$"


def guess_by_url(links):
    #for a look at an archive page, where the links are in whatever order that page lists them and the
    #same page is often linked twice. this only asks what the addresses look like they are grouped by,
    #which is enough to say "these read as 30 issues" without pretending to know the reading order.
    seen, tidy = set(), []
    for where in links:
        if where in seen or not numbers_in(where):
            continue
        seen.add(where)
        tidy.append({"n": len(tidy) + 1, "url": where})
    if len(tidy) < 4:
        return None, 0
    most = max(len(numbers_in(page["url"])) for page in tidy)
    best = None
    for at in range(most):
        keys, numbers = group_by_url(tidy, at)
        if any(key is None for key in keys):
            continue
        counted = {}
        for key, number in zip(keys, numbers):
            counted.setdefault(key, [number, 0])[1] += 1
        if not (2 <= len(counted) <= max(2, len(tidy) // 3)):
            continue
        numbered = [value for value, held in counted.values() if value is not None]
        if len(numbered) != len(counted) or min(numbered) not in (0, 1):
            continue
        named = 1 if re.search(r'(issue|chapter|chap|book|volume|vol|part|arc)',
                               list(counted)[0] or '', re.I) else 0
        score = (named, -len(counted))
        if best is None or score > best[0]:
            #kept in the order the page first mentions each one, which is usually the order they came out
            best = (score, [(chapter_word(key), held) for key, (value, held) in counted.items()])
    if best is None:
        return None, len(tidy)
    return best[1], len(tidy)


def try_archive(folder, args):
    #a look at an archive page on its own: what it would be read as, before a comic is walked for the
    #addresses that would let every heading be turned into a page number
    metadata = read_metadata(folder) if folder and os.path.isdir(folder) else {}
    known = ((metadata.get("settings") or {}).get("url")
             or (metadata.get("history") or {}).get("first_page_url") or args.like)
    if not known:
        print("Nothing says what this comic's page addresses look like. Pass --like with one of its pages.")
        return 2
    reader = ArchiveReader()
    try:
        reader.feed(read_archive(args.archive, args.browser, args.script))
    except (requests.RequestException, OSError) as error:
        print("Could not read {0}: {1}".format(args.archive, error))
        return 1

    #the archive's own order stands in for the comic's, so the very code a real run uses can read it:
    #a preview that worked things out its own way would not be a preview of anything
    archive_links, order = pages_linked(reader.events, args.archive, known)
    pretend = [{"n": at, "url": where} for at, where in enumerate(archive_links, 1)]
    found, pages = chapters_from_events(reader.events, order, args.archive)
    found = settle_chapters(found, pretend) if found and pretend else []

    print("{0}".format(args.archive))
    print("  pages of this comic linked: {0}, looking like {1}".format(len(archive_links), known))
    print("  chapters it would read: {0}".format(len(found)))
    for chapter in found[:40]:
        print("  {0:<4} {1:<46} {2:>4} page(s) listed, starts at {3}".format(
            chapter["number"], (chapter["label"] or "")[:46], chapter["pages"],
            (chapter["start_url"] or "")[-52:]))
    if len(found) > 40:
        print("  ... and {0} more".format(len(found) - 40))
    said = [chapter["pages_said"] for chapter in found if chapter.get("pages_said")]
    if said:
        print("  {0} of these say how long they are, adding up to {1} page(s), against {2} page(s) "
              "linked here".format(len(said), sum(said), len(archive_links)))
        if sum(said) > len(archive_links) * 1.5:
            print("      so this page lists where chapters start, not every page: the comic has to be "
                  "walked for the pages in between.")
        quiet = [chapter for chapter in found if not chapter.get("pages_said")]
        if quiet and len(quiet) <= max(3, len(found) // 10):
            #on a page where almost every heading states a length, one that does not is usually not a
            #chapter at all but some other section that happens to link into the comic
            print("      {0} of them say nothing about their length, unlike the rest, so look at "
                  "whether they are chapters at all:".format(len(quiet)))
            for chapter in quiet[:5]:
                print("        {0:<40} starts at {1}".format(
                    (chapter["label"] or "")[:40], (chapter["start_url"] or "")[-46:]))
    if not found:
        print("  Nothing was read as a chapter. Either no link on that page is a page of this comic - check "
              "what --like says they look like - or the page needs --browser to build itself first.")
        return 1
    #an archive with no chapter headings reads as one heading over everything, which says nothing about
    #the comic. the addresses it links to might still say where the chapters are, so they are tried here.
    biggest = max((chapter["pages"] for chapter in found), default=0)
    if len(found) < 3 or biggest > len(archive_links) * 0.8:
        by_url, distinct = guess_by_url(archive_links)
        print()
        if by_url:
            print("  The headings say little, but the addresses do: {0} chapter(s) across {1} distinct "
                  "page(s).".format(len(by_url), distinct))
            for at, (label, held) in enumerate(by_url[:8], 1):
                print("  {0:<4} {1:<40} {2:>4} page(s)".format(at, label[:40], held))
            if len(by_url) > 8:
                print("  ... and {0} more".format(len(by_url) - 8))
            print("  Run chapters.py chapters <folder> with no --archive to use those; the comic's own "
                  "order decides where each one starts.")
        else:
            print("  Neither the headings nor the addresses say where chapters start here. A list of "
                  "chapter starts (--list) is the way in.")
    print("  Nothing was saved. This only says how the page reads; page numbers need the comic walked "
          "once (chapters.py index).")
    return 0


def plan(folder, args):
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    metadata = read_metadata(folder)
    known = metadata.get("chapters") or {}
    if (not args.archive and not args.list and not args.urls
            and known.get("source") == "archive" and known.get("source_url")):
        #the comic remembers where its chapters are listed, so keeping them current needs no arguments
        args.archive = known["source_url"]
        print("Reading the archive this comic remembers: {0}".format(args.archive))
    listed = None
    if args.archive and not args.urls:
        found, listed = chapters_from_archive(args.archive, pages, args.browser, args.script)
        source, source_url = "archive", args.archive
    elif args.list:
        found, source, source_url = chapters_from_list(args.list, pages), "list", None
    elif known.get("source") == "hand" and known.get("fixes"):
        #this comic's chapters were set by hand, so there is nothing to re-read: the corrections are the
        #source, and working the addresses out afresh would throw them away
        print("This comic's chapters were set by hand; keeping them.")
        found, source, source_url = [], "hand", None
    else:
        found, source, source_url = chapters_from_urls(pages), "urls", None
        if not found:
            print("Nothing in this comic's addresses says where a chapter starts. Give --archive with its "
                  "archive page, --list with a file of chapter start addresses, or set the boundaries by "
                  "hand with chapters.py fix.")
            return 1
    if not found and source != "hand":
        print("No chapters found.")
        return 1
    found, took, missed = apply_fixes(found, pages, known.get("fixes"))
    say_fixes(took, missed)
    chapters = settle_chapters(found, pages, args.shift)
    show_chapters(folder, chapters, pages, listed)
    how, what = compare_chapters(known.get("list"), chapters)
    if known.get("list"):
        if how == "same":
            print("  the same chapters as before.")
        elif how == "longer":
            print("  {0} chapter(s) more than before: {1}".format(
                len(what), ", ".join("{0} at page {1}".format(label, at) for at, label in what[:4])))
        else:
            print("  WARNING: this moves chapters that already have archives written for them: {0}{1}".format(
                ["page {0}".format(at) for at, label in what[:4]], "..." if len(what) > 4 else ""))
    if len(chapters) < 2 and not args.force:
        #a comic in one chapter is a comic that is not chaptered. saving this replaces the single archive
        #with a single archive under another name, which is the sort of thing that looks like it worked.
        print("  this reads as one chapter over the whole comic, which is what a page with no chapter "
              "headings looks like - not a comic in one chapter. Nothing saved. Use --archive with a "
              "page that does list chapters, --urls if the addresses number them, or --list.")
        return 1
    if not args.save:
        print("  nothing saved. Run it again with --save once this looks right.")
        return 0
    if how == "changed" and not args.force:
        print("  nothing saved, because pages would move between archives that already exist. Look at it, "
              "then run it again with --force if that is what you want.")
        return 1
    code = save_chapters(folder, chapters, source, source_url)
    if not code and how != "same" and known.get("packed"):
        #nothing repacks itself: an archive holding the old boundary keeps holding it until pack is run
        print("  the chapter archives still hold the old boundaries. Run: chapters.py pack {0}".format(folder))
    return code


# ---------------- one archive per chapter ----------------
def tidy_name(text):
    #a label becomes part of a filename, so anything a filesystem or a reader would choke on goes
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', text or "")
    text = re.sub(r'\s+', ' ', text).strip(' .')
    return text[:70].strip() or "Chapter"


def chapter_folder(folder, metadata, root=None, given=None):
    #the comic's own folder inside the archive shelf: a reader that dislikes loose .cbz files in a shelf
    #is happy with one folder per comic. a comic whose single archive already sits in a folder of its own
    #name is given that folder, rather than another one nested inside it.
    if given:
        return given
    cbz = (metadata.get("settings") or {}).get("cbz_path")
    if not cbz:
        return os.path.abspath(folder) + "_chapters"
    full = cbz if os.path.isabs(cbz) or not root else os.path.join(root, cbz.replace('/', os.sep))
    name = os.path.basename(os.path.abspath(folder))
    if os.path.basename(os.path.dirname(full)).lower() == name.lower():
        return os.path.dirname(full)
    return full[:-4] if full.lower().endswith(".cbz") else full


def chapter_file(folder, chapter):
    return "{0} - c{1:03d} - {2}.cbz".format(os.path.basename(os.path.abspath(folder)),
                                             chapter["number"], tidy_name(chapter["label"]))


def comic_info(folder, chapter, count, names):
    #what a reader reads to know this is chapter N of a series rather than a loose pile of pictures
    def escaped(text):
        return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             '  <Series>{0}</Series>'.format(escaped(os.path.basename(os.path.abspath(folder)))),
             '  <Number>{0}</Number>'.format(chapter["number"]),
             '  <Count>{0}</Count>'.format(count),
             '  <Title>{0}</Title>'.format(escaped(chapter["label"])),
             '  <PageCount>{0}</PageCount>'.format(len(names))]
    if chapter.get("start_url"):
        lines.append('  <Web>{0}</Web>'.format(escaped(chapter["start_url"])))
    lines.append('  <Notes>Made by chapters.py from pages {0} to {1}</Notes>'.format(
        chapter["start_page"], chapter["end_page"]))
    lines.append('</ComicInfo>')
    return chr(10).join(lines) + chr(10)


def chapter_contents(folder, chapters, pages):
    #which files belong to which chapter, in reading order. a page the comic has and this folder does not
    #simply is not there; the pages either side of it still sit in the right chapter.
    by_page = {page["n"]: page for page in pages}
    parcels, otherwise = [], []
    for chapter in chapters:
        names = []
        for n in range(chapter["start_page"], chapter["end_page"] + 1):
            name = (by_page.get(n) or {}).get("file")
            if not name:
                continue
            #a page held as a video, as flash, or as a note saying where it lives now stays in the
            #parcel: the packing puts a stand-in in the archive where it belongs, saying where to go
            if held_otherwise(folder, name):
                otherwise.append(name)
            names.append(name)
        parcels.append((chapter, names))
    if otherwise:
        print("  {0} page(s) no reader can show, which the archives get a stand-in for: {1}{2}".format(
            len(otherwise), otherwise[:3], "..." if len(otherwise) > 3 else ""))
    #a page the site no longer serves cannot be in `pages`, because the walk never saw it. it still has
    #to end up in a chapter, or packing would refuse to write around it.
    held = folder_pages(folder)
    recovered = recovered_files(folder)
    if parcels and recovered:
        placed = place_recovered(held, parcels, recovered)
        if placed:
            print("  {0} page(s) the site no longer serves, put back by hand, kept where they read: "
                  "{1}{2}".format(len(placed), placed[:3], "..." if len(placed) > 3 else ""))
    #pages saved since the chapters were worked out belong to the chapter still being published, which is
    #the last one. they are added in the order they were saved, which is the order they came out.
    if parcels:
        known = {name for _, names in parcels for name in names}
        last_known = max((at for at, name in enumerate(held) if name in known), default=-1)
        fresh = [name for name in held[last_known + 1:] if name not in known]
        if fresh:
            parcels[-1][1].extend(fresh)
            print("  {0} page(s) saved since the chapters were worked out join chapter {1}".format(
                len(fresh), parcels[-1][0]["number"]))
    return parcels


def already_packed(path, names, folder):
    #an archive only needs writing again if what it holds is not what it should hold
    if not os.path.exists(path):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            held = {info.filename: info.file_size for info in zf.infolist() if not info.filename.endswith('/')}
    except (OSError, zipfile.BadZipFile):
        return False
    wanted = {}
    for name in names:
        entry, made = archive_entry(folder, name)
        if made is not None:
            #a stand-in is drawn the same way every time, so its size is what says it is already there
            wanted[entry] = len(made)
            continue
        try:
            wanted[name] = os.path.getsize(os.path.join(folder, name))
        except OSError:
            return False
    held.pop("ComicInfo.xml", None)
    return held == wanted


def pack(folder, args):
    metadata = read_metadata(folder)
    if (metadata.get("settings") or {}).get("cbz") is False and not args.force:
        print("{0} is set to keep no archives (cbz is off in its settings), so nothing was written. Turn "
              "that on, or pass --force to write them anyway.".format(folder))
        return 0
    chapters = (metadata.get("chapters") or {}).get("list")
    if not chapters:
        print("ERROR: no chapters worked out for {0} yet. Run: chapters.py chapters {0} --archive ...".format(folder))
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    shelf = chapter_folder(folder, metadata, args.root, args.cbz_folder)
    parcels = chapter_contents(folder, chapters, pages)
    held = {name for _, names in parcels for name in names}
    print("  listing what is in the comic's folder ...", flush=True)
    on_disk = set(folder_pages(folder, others=True))
    astray = sorted(on_disk - held)
    if astray:
        print("ERROR: {0} file(s) belong to no chapter, so nothing was written: {1}{2}".format(
            len(astray), astray[:5], "..." if len(astray) > 5 else ""))
        return 1

    print("{0}: {1} chapter(s) into {2}".format(folder, len(parcels), shelf))
    print("  looking at what the archives already hold ...", flush=True)
    todo = []
    for at, (chapter, names) in enumerate(parcels, 1):
        if not already_packed(os.path.join(shelf, chapter_file(folder, chapter)), names, folder):
            todo.append((chapter, names))
        if at % 10 == 0 and at < len(parcels):
            print("    looked at {0} of {1}".format(at, len(parcels)), flush=True)
    print("  {0} to write, {1} already as they should be".format(len(todo), len(parcels) - len(todo)))
    for chapter, names in parcels[:100]:
        mark = "write" if (chapter, names) in todo else "keep "
        print("  {0} c{1:03d} {2:<44} {3:>4} page(s)  {4}".format(
            mark, chapter["number"], tidy_name(chapter["label"])[:44], len(names),
            chapter_file(folder, chapter)[:60]))
    if args.dry_run:
        print("Nothing was written. Run it again without --dry-run.")
        return 0

    if not os.path.isdir(shelf):
        os.makedirs(shelf)
    written = 0
    for chapter, names in todo:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        print("  writing {0} ({1} page(s)) ...".format(os.path.basename(path), len(names)), flush=True)
        spare = path + ".packing"
        with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr("ComicInfo.xml", comic_info(folder, chapter, len(parcels), names))
            for name in names:
                entry, made = archive_entry(folder, name)
                if made is None:
                    zf.write(os.path.join(folder, name), entry)
                else:
                    #a page no reader can show gets a page saying where the real one is, named so it
                    #falls where the page belongs
                    zf.writestr(entry, made)
        os.replace(spare, path)
        written += 1
        print("  wrote {0} ({1} page(s))".format(os.path.basename(path), len(names)), flush=True)
    print("Wrote {0} chapter archive(s).".format(written))

    kept = verify_chapters(folder, shelf, parcels)
    if kept is not True:
        return 1
    metadata = read_metadata(folder)
    block = metadata.setdefault("chapters", {})
    block["folder"] = os.path.relpath(shelf, args.root).replace(os.sep, '/') if args.root else shelf
    block["packed"] = time_stamp()
    #nothing is turned off here: a comic that has chapters is one mirror_base leaves alone, and whether it
    #has archives at all is the one cbz setting, the same switch as for a comic with no chapters
    write_metadata(folder, metadata)

    if args.replace:
        return drop_single(folder, metadata, args)
    return 0


def verify_chapters(folder, shelf, parcels):
    #every page has to be in exactly one chapter archive, at the size it is on disk, before the single
    #archive that holds them all can be given up
    seen, trouble = {}, []
    for chapter, names in parcels:
        path = os.path.join(shelf, chapter_file(folder, chapter))
        try:
            with zipfile.ZipFile(path) as zf:
                held = {info.filename: info.file_size for info in zf.infolist()
                        if info.filename != "ComicInfo.xml" and not info.filename.endswith('/')}
        except (OSError, zipfile.BadZipFile) as error:
            trouble.append("c{0:03d}: {1}".format(chapter["number"], error))
            continue
        for name in names:
            #a page held as something no reader can show is in the archive as its stand-in, so that is
            #what has to be there and at the size the drawing comes to
            entry, made = archive_entry(folder, name)
            size = len(made) if made is not None else os.path.getsize(os.path.join(folder, name))
            if held.get(entry) != size:
                trouble.append("c{0:03d}: {1} is {2} in the archive, {3} on disk".format(
                    chapter["number"], entry, held.get(entry), size))
            if name in seen:
                trouble.append("{0} is in both c{1:03d} and c{2:03d}".format(name, seen[name], chapter["number"]))
            seen[name] = chapter["number"]
    missing = sorted(set(folder_pages(folder, others=True)) - set(seen))
    for name in missing[:5]:
        trouble.append("{0} is in no chapter archive".format(name))
    if trouble:
        print("Checked the chapter archives and found {0} problem(s):".format(len(trouble)))
        for line in trouble[:10]:
            print("  {0}".format(line))
        return False
    print("Checked: all {0} page(s) are in exactly one chapter archive, at the size they are on disk.".format(
        len(seen)))
    return True


def drop_single(folder, metadata, args):
    cbz = (metadata.get("settings") or {}).get("cbz_path")
    if not cbz:
        return 0
    full = cbz if os.path.isabs(cbz) else os.path.join(args.root or os.path.dirname(folder),
                                                       cbz.replace('/', os.sep))
    if not os.path.exists(full):
        return 0
    size = os.path.getsize(full)
    os.remove(full)
    print("Removed {0} ({1:.0f} MB); the chapter archives hold every page it held.".format(full, size / 1e6))
    return 0


# ---------------- fetching pages again ----------------
def joined_pages(folder, args):
    #the alignment says which file is which page; the walk says how big the site's copy is
    cache = index_path(folder, args.root, args)
    alignment = cache.replace(".jsonl", ".align.json")
    if not os.path.exists(alignment):
        print("ERROR: {0} has not been lined up yet. Run: chapters.py index {0}".format(folder))
        return None
    #a library on a network share answers slowly enough that silence looks like a hang, so every slow
    #step says what it is doing before it starts rather than after it finishes
    print("  reading which file is which page ...", flush=True)
    sizes = {page["n"]: page.get("bytes") for page in read_index(cache)}
    saved = json.load(open(alignment, encoding='utf-8'))
    if not saved.get("settled"):
        print("WARNING: this comic's alignment is not settled, so which file is which page is not certain.")
    return [dict(page, bytes=sizes.get(page["n"])) for page in saved["pages"]]


def refetch(folder, args):
    #the copies in a library that came from somewhere else are often compressed harder than what the site
    #serves. this fetches those pages again under the names they already have, so nothing else has to change
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    only = set()
    if args.page:
        try:
            only = {int(bit) for bit in str(args.page).replace(',', ' ').split()}
        except ValueError:
            print("ERROR: --page takes page numbers, such as --page 1 or --page 1,5,9.")
            return 2
    wanted = []
    for page in pages:
        if not page["file"] or not page.get("src"):
            continue
        path = os.path.join(folder, page["file"])
        try:
            held = os.path.getsize(path)
        except OSError:
            continue
        if only:
            if page["n"] in only:
                wanted.append((page, held))
        elif args.all or (page["bytes"] and held != page["bytes"]):
            wanted.append((page, held))
    if only:
        missed = only - {page["n"] for page, _ in wanted}
        if missed:
            print("ERROR: no page {0} with a file and a known image here.".format(sorted(missed)))
            return 2
    if not wanted:
        print("Nothing to fetch again: every page is already the size the site serves.")
        return 0

    growth = sum((page["bytes"] or held) - held for page, held in wanted)
    print("{0} page(s) to fetch again, {1:.0f} MB held here now, {2:.0f} MB on the site ({3:+.0f} MB)".format(
        len(wanted), sum(held for _, held in wanted) / 1e6,
        sum((page["bytes"] or held) for page, held in wanted) / 1e6, growth / 1e6))
    if args.dry_run:
        for page, held in wanted[:8]:
            print("  page {0:<5} {1:<26} {2} -> {3} bytes".format(
                page["n"], page["file"][:26], held, page["bytes"]))
        if len(wanted) > 8:
            print("  ... and {0} more".format(len(wanted) - 8))
        print("Nothing was changed. Run it again without --dry-run to fetch them.")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    done, kept, failed, renamed = 0, 0, [], []
    for page, held in wanted:
        path = os.path.join(folder, page["file"])
        try:
            answer = session.get(page["src"], timeout=120)
            answer.raise_for_status()
            fresh = answer.content
        except requests.RequestException as error:
            failed.append((page["n"], str(error)[:80]))
            continue
        #only replaced once the new copy is in hand and is the size the site said, so a failed fetch
        #cannot leave a page half written or lose the copy that was already there
        if page["bytes"] and len(fresh) != page["bytes"]:
            failed.append((page["n"], "fetched {0} bytes, expected {1}".format(len(fresh), page["bytes"])))
            continue
        if not args.as_named and len(fresh) <= held:
            kept += 1
            continue
        if args.as_named:
            #the file here is not this page's image at all - a scrape that matched the site's banner or an
            #author icon instead of the comic. the right copy belongs under the right name, so the wrong
            #one goes rather than being overwritten and keeping a name that was never true.
            want = os.path.basename(page["src"].split('?')[0])
            if not want.lower().endswith(".png"):
                want += ".png"
            number = re.match(r'^(\d{1,6})_', page["file"])
            if number:
                want = "{0}_{1}".format(number.group(1), want)
            if want != page["file"]:
                if os.path.exists(os.path.join(folder, want)):
                    failed.append((page["n"], "{0} is already here".format(want)))
                    continue
                renamed.append((page["n"], page["file"], want))
                path = os.path.join(folder, want)
        spare = path + ".fetching"
        with open(spare, 'wb') as f:
            f.write(fresh)
        os.replace(spare, path)
        for at, was, now in renamed[-1:]:
            if at == page["n"] and os.path.exists(os.path.join(folder, was)):
                os.remove(os.path.join(folder, was))
                print("  page {0}: {1} was not this page; saved {2} instead".format(at, was, now))
        done += 1
        if done % 25 == 0:
            print("  {0} of {1} replaced".format(done, len(wanted)))
    if renamed:
        #the alignment names the file for each page, so it has to learn the new ones or everything after
        #this looks at a file that is no longer there
        alignment = index_path(folder, args.root, args).replace(".jsonl", ".align.json")
        saved = json.load(open(alignment, encoding='utf-8'))
        fresh_names = {at: now for at, _, now in renamed}
        for page in saved["pages"]:
            if page["n"] in fresh_names:
                page["file"] = fresh_names[page["n"]]
        spare = alignment + ".writing"
        with open(spare, 'w', encoding='utf-8') as f:
            json.dump(saved, f, indent=1)
            f.write(chr(10))
        os.replace(spare, alignment)
        print("  {0} name(s) put right in the alignment too.".format(len(renamed)))
    print("Replaced {0} page(s); left {1} alone as no better than what was here.".format(done, kept))
    for n, why in failed[:8]:
        print("  page {0} was not replaced: {1}".format(n, why))
    if len(failed) > 8:
        print("  ... and {0} more".format(len(failed) - 8))
    if done and args.repack:
        repack(folder, args)
    elif done:
        print("The .cbz still holds the old copies. Run again with --repack, or repack it yourself.")
    return 1 if failed else 0


def repack(folder, args):
    #a zip cannot replace an entry in place, so the archive is written afresh beside the old one and
    #swapped in only once it is complete and holds every page
    cbz = args.cbz
    if not cbz:
        metadata = read_metadata(folder)
        cbz = (metadata.get("settings") or {}).get("cbz_path")
        if cbz and args.root and not os.path.isabs(cbz):
            cbz = os.path.join(args.root, cbz)
    if not cbz or not os.path.exists(cbz):
        print("No archive found to repack; pass --cbz with its path.")
        return 1
    names = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    with zipfile.ZipFile(cbz) as zf:
        prefix = os.path.basename(os.path.abspath(folder)) + '/'
        held = zf.namelist()
        prefix = prefix if held and all(name.startswith(prefix) for name in held) else ''
    spare = cbz + ".packing"
    print("Repacking {0} ({1} file(s)) ...".format(cbz, len(names)))
    with zipfile.ZipFile(spare, 'w', zipfile.ZIP_STORED) as zf:
        for name in names:
            zf.write(os.path.join(folder, name), prefix + name)
    with zipfile.ZipFile(spare) as zf:
        packed = [name for name in zf.namelist() if not name.endswith('/')]
    if len(packed) != len(names):
        os.remove(spare)
        print("ERROR: the new archive holds {0} of {1} files, so the old one was left alone.".format(
            len(packed), len(names)))
        return 1
    shutil.move(spare, cbz)
    print("  {0} now holds every page as it is on disk.".format(cbz))
    return 0


def walk(folder, args):
    #the slow part: mirror_base follows the comic from its first page, saving nothing
    cache = index_path(folder, args.root, args)
    start = args.start
    if getattr(args, "restart", False) and os.path.exists(cache):
        #a record written from somewhere other than the first page cannot be carried on from: its page
        #numbers are counted from wherever it began, and a walk resuming from its last line starts at the
        #comic's newest page and stops there. said plainly and thrown away, rather than merged into.
        held = read_index(cache)
        print("Throwing away the record of {0} page(s) in {1}, and walking from the start.".format(
            len(held), cache))
        os.remove(cache)
    metadata = read_metadata(folder)
    history = metadata.get("history") or {}
    if not start and not os.path.exists(cache):
        if history.get("first_page_number") in (0, 1) and history.get("first_page_url"):
            start = history["first_page_url"]
        else:
            start = (metadata.get("settings") or {}).get("url")
            if not start:
                print("ERROR: nothing says where {0} starts. Pass --start with its first page.".format(folder))
                return None
            print("NOTE: this comic's metadata only records page {0} at {1}, so the walk starts from where "
                  "it left off and follows the comic's first-page link back.".format(
                      history.get("first_page_number"), start))
            args.first = True
    command = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_base.py"),
               "--index", cache]
    #a walk drives the same site a scrape does, so it needs to be told the same things about it. a comic
    #whose pages are built by javascript shows nothing at all without it - not its images and not its next
    #link - so a walk without these settings ends on the page it started, having seen nothing.
    settings = metadata.get("settings") or {}
    if settings.get("javascript"):
        command.append("--enable_javascript")
    if settings.get("firefox"):
        command.append("--firefox")
    if settings.get("waittime"):
        command += ["--waittime", str(settings["waittime"])]
    if args.first:
        command.append("--index-first")
    if args.limit:
        command += ["--index-limit", str(args.limit)]
    if start:
        command.append(start)
    else:
        #carrying on, so the walk works out where it got to from the cache itself
        command.append(read_index(cache)[-1]["url"])
    print("Walking {0} ...".format(folder))
    done = subprocess.run(command, text=True)
    if done.returncode != 0:
        print("The walk stopped early (exit {0}); what it got is kept and running it again carries "
              "on.".format(done.returncode))
    return cache


def by_written_order(folder, pages, files):
    #for a comic this scraper downloaded itself, in one pass, without numbering the files: the order the
    #files were written IS the order the pages were published, because that is the order they were
    #fetched. it needs no names and no sizes, which is what makes it work on a site that serves
    #jan.png for one page and 99002.jpg for the next.
    if len(files) != len(pages):
        print("ERROR: {0} file(s) here but {1} page(s) walked. Lining up by when files were written "
              "needs one of each, so this comic needs the usual alignment.".format(len(files), len(pages)))
        return None, None
    stamped = []
    for name in files:
        try:
            stamped.append((os.path.getmtime(os.path.join(folder, name)), name))
        except OSError as error:
            print("ERROR: could not read when {0} was written: {1}".format(name, error))
            return None, None
    stamped.sort()
    ties = sum(1 for one, next_one in zip(stamped, stamped[1:]) if one[0] == next_one[0])
    if ties:
        print("  {0} file(s) share a write time with the next, so their order between themselves is "
              "guesswork; the sizes below say whether it landed right.".format(ties))
    return [name for _, name in stamped], ["time"] * len(pages)


def do_align(folder, args):
    cache = index_path(folder, args.root, args)
    if not os.path.exists(cache):
        print("ERROR: no index for {0} yet. Run: chapters.py index {1}".format(folder, folder))
        return 2
    pages = read_index(cache)
    #a page the site has lost belongs to no walked page, so it takes no part in the lining up: left in,
    #it would leave a stretch with one more file than pages and nothing would settle
    recovered = recovered_files(folder)
    #videos count here, and only here: a page held as one is a page this folder has, and leaving it out
    #made it read as a page gone missing and the file itself as something nothing claims
    held = folder_pages(folder, others=True)
    files = [name for name in held if name not in recovered]
    rescued = [name for name in held if name in recovered]
    fill_sizes(cache, pages)
    if args.by_time:
        aligned, how = by_written_order(folder, pages, files)
        if aligned is None:
            return 2
        anchors, trouble = [], []
    else:
        aligned, how, anchors, trouble = align(pages, files, folder)
    settled = describe(folder, pages, files, aligned, how, anchors, trouble, rescued, recovered)
    where = save_alignment(cache.replace(".jsonl", ".align.json"), folder, pages, aligned, how, settled)
    remember_cache(folder, cache)
    print("  written to {0}".format(where))
    if settled:
        save_gaps(folder, pages, aligned)
    return 0 if settled else 1


def plain_name(name):
    #a name this script has already numbered, back to whatever the site called it
    return re.sub(r'^\d{1,6}_', '', name)


def renumber(folder, args):
    #a comic scraped without --prefix keeps the site's own names, and a site that calls one page jan.png
    #and the next 99002.jpg reads in no order at all. the alignment is the only thing that knows which
    #file is which page, so the numbers come from there and from nothing else.
    cache = index_path(folder, args.root, args)
    alignment = cache.replace(".jsonl", ".align.json")
    if not os.path.exists(alignment):
        print("ERROR: {0} has not been lined up yet. Run: chapters.py index {0}".format(folder))
        return 2
    saved = json.load(open(alignment, encoding='utf-8'))
    if not saved.get("settled") and not args.force:
        print("ERROR: this comic's alignment is not settled, so which file is which page is not certain "
              "and numbering them would write that uncertainty into their names. Sort the alignment out "
              "first, or pass --force if you are sure.")
        return 2
    held = set(os.listdir(folder))
    moves, already = [], 0
    for page in saved["pages"]:
        name = page.get("file")
        if not name:
            continue
        want = "{0:04d}_{1}".format(page["n"], plain_name(name))
        if want == name:
            already += 1
        else:
            moves.append((name, want))
    if not moves:
        print("{0}: all {1} file(s) already carry their page number.".format(folder, already))
        return 0
    #every page must want a name of its own, and must not want one that belongs to a file staying put
    wanted = [want for _, want in moves]
    twice = sorted({want for want in wanted if wanted.count(want) > 1})
    staying = held - {name for name, _ in moves}
    taken = sorted(want for want in wanted if want in staying)
    if twice or taken:
        print("ERROR: these names would collide, so nothing was renamed:")
        for want in (twice + taken)[:10]:
            print("      {0}".format(want))
        return 2
    print("{0}: {1} file(s) to number, {2} already numbered".format(folder, len(moves), already))
    for name, want in moves[:4]:
        print("      {0}  ->  {1}".format(name[:44], want[:44]))
    if len(moves) > 4:
        print("      ... and {0} more".format(len(moves) - 4))
    if args.dry_run:
        print("  nothing was renamed. Run it again without --dry-run once this looks right.")
        return 0
    #moved through names nothing else can hold, so a file never lands on one still waiting to be moved
    stepped = []
    try:
        for at, (name, want) in enumerate(moves):
            step = os.path.join(folder, "{0}.renaming{1}".format(want, at))
            os.rename(os.path.join(folder, name), step)
            stepped.append((name, step, want))
        for _, step, want in stepped:
            os.rename(step, os.path.join(folder, want))
    except OSError as error:
        print("ERROR: renaming stopped: {0}".format(error))
        print("  putting back the {0} file(s) that had moved ...".format(len(stepped)))
        for name, step, _ in stepped:
            if os.path.exists(step):
                os.rename(step, os.path.join(folder, name))
        print("  nothing was renamed in the end.")
        return 2
    print("  {0} file(s) renamed.".format(len(moves)))
    renamed = dict(moves)
    for page in saved["pages"]:
        if page.get("file") in renamed:
            page["file"] = renamed[page["file"]]
    spare = alignment + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(saved, f, indent=1)
        f.write(chr(10))
    os.replace(spare, alignment)
    metadata = read_metadata(folder)
    if metadata:
        settings = metadata.setdefault("settings", {})
        if not settings.get("prefix"):
            settings["prefix"] = True
            print("  this comic now saves new pages with their number too (prefix is on).")
        write_metadata(folder, metadata)
    print("  the archive still holds the old names: chapters.py repack {0} --root <library>, or pack "
          "for a chaptered comic.".format(folder))
    return 0


def saved_as(src):
    #the name a scrape would give this image, worked out here rather than taken from the walk's record,
    #so putting a page in does not depend on that record being right about it
    name = os.path.basename(src.split('?')[0].rstrip('/'))
    kind = "gif" if "gif" in src.lower() else "png"
    return name if name.lower().endswith(kind) else "{0}.{1}".format(name, kind)


def one_page(url, args):
    #what a single page holds, found the way a scrape finds it: the element paths this script knows,
    #in a real browser. a walk of one page into a scratch index is exactly that, and needs no new mode.
    spare = os.path.join(config_folder(), "index", "one-page-{0}.jsonl".format(os.getpid()))
    if not os.path.isdir(os.path.dirname(spare)):
        os.makedirs(os.path.dirname(spare))
    command = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_base.py"),
               "--index", spare, "--index-limit", "1", url]
    try:
        subprocess.run(command, text=True)
        held = read_index(spare)
    finally:
        if os.path.exists(spare):
            os.remove(spare)
    return held[0] if held else None


def shift_up(folder, pages, at):
    #every page from here on moves one place along, so the new page has a place of its own. renamed from
    #the back, so a file never lands on one that has not moved yet.
    moved = []
    for page in reversed(pages):
        if page["n"] < at or not page.get("file"):
            continue
        want = "{0:04d}_{1}".format(page["n"] + 1, plain_name(page["file"]))
        if want == page["file"]:
            continue
        os.rename(os.path.join(folder, page["file"]), os.path.join(folder, want))
        moved.append((page["n"], page["file"], want))
    return moved


def insert_page(folder, args):
    #a page the comic's own next links skip - powerpuffgirls has one the archive lists and the navigation
    #walks straight past - can be reached by nothing that follows the comic. so it is put in by hand: the
    #page is read, its image saved, and everything after it moves along one so the order still reads true.
    if not args.url or not args.after:
        print("ERROR: say which page to put in with --url, and which page it follows with --after.")
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    by_file = [page for page in pages if page.get("file")]
    if not by_file or not all(page_number(page["file"]) is not None for page in by_file):
        print("ERROR: this comic's files do not carry their page numbers, so there is nowhere to put one "
              "in without guessing. Run: chapters.py renumber {0}".format(folder))
        return 2
    after = page_at(pages, args.after) if not str(args.after).strip().isdigit() else int(args.after)
    if not after or after > len(pages):
        print("ERROR: {0} is not a page of this comic.".format(args.after))
        return 2
    if page_at(pages, args.url):
        print("This comic already holds {0}, as page {1}.".format(args.url, page_at(pages, args.url)))
        return 0
    at = after + 1
    print("{0} goes in at page {1}, after {2}".format(args.url, at, pages[after - 1]["url"]))
    found = one_page(args.url, args)
    if not found or not found.get("src"):
        print("ERROR: no comic image was found on {0}. Check it in the browser, or add an element path "
              "for this site.".format(args.url))
        return 2
    name = "{0:04d}_{1}".format(at, saved_as(found["src"]))
    #fetched before anything is moved, so a page that cannot be had leaves the comic exactly as it was
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        answer = session.get(found["src"], timeout=120)
        answer.raise_for_status()
    except requests.RequestException as error:
        print("ERROR: could not fetch {0}: {1}".format(found["src"], error))
        return 2
    print("  {0} bytes from {1}".format(len(answer.content), found["src"]))
    if args.dry_run:
        print("  it would be saved as {0}, and {1} page(s) after it would move along one. Nothing was "
              "changed.".format(name, len(pages) - after))
        return 0

    moved = shift_up(folder, pages, at)
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(answer.content)
    print("  saved {0}; {1} page(s) after it moved along one".format(name, len(moved)))

    #the index is what says the comic's order, so it learns the page too: no walk can reach it, and a
    #walk that could would have found it already
    cache = index_path(folder, args.root, args)
    lines = read_index(cache)
    fresh = {"n": at, "url": args.url, "src": found["src"], "file": name,
             "title": found.get("title"), "bytes": len(answer.content)}
    out = [line for line in lines if line["n"] < at]
    out.append(fresh)
    for line in lines:
        if line["n"] >= at:
            out.append(dict(line, n=line["n"] + 1,
                            file="{0:04d}_{1}".format(line["n"] + 1, plain_name(line["file"]))
                            if line.get("file") else None))
    spare = cache + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        for line in out:
            f.write(json.dumps(line) + chr(10))
    os.replace(spare, cache)
    print("  the walk's own record now holds {0} page(s)".format(len(out)))

    metadata = read_metadata(folder)
    if metadata:
        history = metadata.setdefault("history", {})
        history["inserted"] = (history.get("inserted") or []) + [
            {"page": at, "url": args.url, "file": name, "at": time_stamp(),
             "note": args.note or "the comic's own next links skip this page, so it was put in by hand"}]
        #a chapter starting after this page starts one page later than it did. the page it starts AT has
        #not changed, only its number, so the numbers are moved and nothing is re-read.
        block = metadata.get("chapters") or {}
        shifted = [chapter for chapter in (block.get("list") or []) if chapter.get("start_page", 0) >= at]
        for chapter in shifted:
            chapter["start_page"] += 1
        for chapter in block.get("list") or []:
            if chapter.get("end_page", 0) >= at:
                chapter["end_page"] += 1
                chapter["pages"] = chapter["end_page"] - chapter["start_page"] + 1
        if block.get("list"):
            #the files those chapters hold are named after their page numbers, so the ones past here have
            #all been renamed and their archives no longer hold what they should
            print("  {0} chapter(s) start later than they did; their archives need writing again: "
                  "chapters.py pack {1}".format(len(shifted), folder))
        write_metadata(folder, metadata)
    print()
    return do_align(folder, args)


def mark_recovered(folder, args):
    #a page the site has lost, found somewhere else and put in the folder by hand. saying so once keeps
    #every later run from calling it a stray, and keeps it in the chapter it reads in when packing.
    metadata = read_metadata(folder)
    if not metadata:
        print("ERROR: no metadata in {0}.".format(folder))
        return 2
    history = metadata.setdefault("history", {})
    held = list(history.get("recovered") or [])
    if not args.file and not args.clear:
        print("{0}: {1} page(s) put back by hand".format(folder, len(held)))
        for one in held:
            there = os.path.exists(os.path.join(folder, str(one.get("file"))))
            print("  {0:<36} {1}{2}".format(str(one.get("file"))[:36], (one.get("note") or "")[:46],
                                            "" if there else "   (no longer in this folder)"))
        if not held:
            print("  none. Use --file <name> once you have put one there.")
        return 0
    if args.clear:
        print("forgotten: all {0}".format(len(held)))
        held = []
    if args.file:
        name = os.path.basename(str(args.file))
        if not args.forget and not os.path.exists(os.path.join(folder, name)):
            print("ERROR: {0} is not in {1}. Put the page there first, named so it sorts where it "
                  "reads.".format(name, folder))
            return 2
        held = [one for one in held if one.get("file") != name]
        if args.forget:
            print("forgotten: {0}".format(name))
        else:
            held.append({"file": name, "note": args.note or "the site no longer serves this page",
                         "at": time_stamp()})
            print("noted: {0} is a page this comic has and the site does not".format(name))
    if held:
        history["recovered"] = held
    else:
        history.pop("recovered", None)
    write_metadata(folder, metadata)
    if not args.forget and not args.clear:
        print("  line the comic up again so it settles around it: chapters.py align {0}".format(folder))
    return 0


def list_fixes(fixes, pages):
    if not fixes:
        print("  nothing has been corrected by hand.")
        return
    for fix in fixes:
        at = page_at(pages, fix.get("url")) if fix.get("url") else fix.get("page")
        print("  page {0:<5} {1:<44} {2}".format(
            at if at else "?", "(no chapter starts here)" if fix.get("drop") else (fix.get("label") or ""),
            fix.get("url") or ""))


def edit_fixes(folder, args):
    #a boundary put right by hand. the correction is written down as a correction rather than edited into
    #the list, so working the chapters out again - from a fresh archive reading, or fresh addresses - keeps
    #it. it is anchored to the page's own address, so it still means the same page after the comic grows.
    metadata = read_metadata(folder)
    if not metadata:
        print("ERROR: no metadata in {0}.".format(folder))
        return 2
    pages = joined_pages(folder, args)
    if pages is None:
        return 2
    block = metadata.setdefault("chapters", {})
    fixes = list(block.get("fixes") or [])
    if not args.at and not args.clear:
        print("{0}: {1} correction(s) by hand".format(folder, len(fixes)))
        list_fixes(fixes, pages)
        return 0
    if args.clear:
        print("forgotten: all {0} correction(s)".format(len(fixes)))
        fixes = []
    if args.at:
        where, at = str(args.at).strip(), None
        if re.match(r'^\d+$', where):
            at = int(where)
            page = next((p for p in pages if p["n"] == at), None)
            if page is None:
                print("ERROR: this comic has no page {0}; it has {1}.".format(at, len(pages)))
                return 2
            where = page["url"]
        else:
            at = page_at(pages, where)
            if at is None:
                print("ERROR: {0} is not a page of this comic. Give one of its page addresses, or a page "
                      "number.".format(where))
                return 2
        if not args.drop and not args.forget and not args.label:
            print("ERROR: say what the chapter starting there is called, with --label, or say --drop for "
                  "no chapter there, or --forget to take back an earlier correction.")
            return 2
        fixes = [fix for fix in fixes if same_page(str(fix.get("url") or "")) != same_page(where)]
        if args.label:
            #a chapter is corrected to one place, not to every place it has been moved to in turn
            fixes = [fix for fix in fixes if (fix.get("label") or "") != args.label]
        if args.forget:
            print("forgotten: whatever was said about page {0}".format(at))
        elif args.drop:
            fixes.append({"url": where, "drop": True, "made": time_stamp()})
            print("noted: no chapter starts at page {0}".format(at))
        else:
            fixes.append({"url": where, "label": args.label, "made": time_stamp()})
            print("noted: page {0} starts {1}".format(at, args.label))
    if fixes:
        block["fixes"] = fixes
    else:
        block.pop("fixes", None)
    stored = block.get("list") or []
    if stored or fixes:
        #with nothing worked out yet, the corrections are the whole of it: a comic whose site says nowhere
        #where its chapters start is chaptered by hand, one boundary at a time, and that is a source like
        #any other rather than something that has to wait for a rule to find nothing first.
        found, took, missed = apply_fixes([dict(chapter) for chapter in stored], pages, fixes)
        say_fixes(took, missed)
        chapters = settle_chapters(found, pages)
        block["list"] = [chapter_record(chapter) for chapter in chapters]
        block["checked"] = time_stamp()
        if not stored:
            block.setdefault("source", "hand")
        print()
        show_chapters(folder, chapters, pages)
    if args.forget or args.clear:
        print("  a correction taken back does not bring the old boundary back on its own. Run "
              "chapters.py chapters {0} --save to work them out afresh.".format(folder))
    write_metadata(folder, metadata)
    if not (stored and block.get("packed")):
        #nothing has been written for these chapters yet, so there is nothing to put right
        return 0
    if args.no_repack:
        print("  the chapter archives still hold the old boundaries: chapters.py pack {0}".format(folder))
        return 0
    #an archive holding a boundary this just corrected is a wrong archive, and a correction that leaves
    #one behind has not finished. only the archives whose contents changed are written again.
    print()
    return pack(folder, args)


def setup():
    params = argparse.ArgumentParser(
        description="Line a comic's saved files up with the pages they came from.")
    params.add_argument("what", choices=["index", "align", "show", "chapters", "fix", "try", "pack",
                                         "refetch", "repack", "renumber", "recovered", "insert"],
                        help="index: walk the comic and line it up. align: line up a walk already done. "
                             "show: what the last alignment says. refetch: fetch again any page whose file "
                             "is not what the site serves. chapters: work out where the chapters start. "
                             "try: read an archive page and say what it would be read as, before walking "
                             "anything. "
                             "fix: put a chapter boundary right by hand. "
                             "renumber: rename the files so each carries its page number. "
                             "recovered: note a page the site has lost that you put back by hand. "
                             "insert: put in a page the comic's own links skip past. "
                             "pack: write one .cbz per chapter. "
                             "repack: write the .cbz afresh from the folder.")
    params.add_argument("folder", help="The comic's folder.")
    params.add_argument("--start", default=None, help="The comic's first page, when its metadata does not know.")
    params.add_argument("--restart", action='store_true', default=False,
                        help="With index, throw away what is already recorded and walk the comic from the "
                             "start. For a record that begins somewhere other than the first page, which "
                             "cannot be carried on from because its page numbers count from the wrong place.")
    params.add_argument("--first", action='store_true', default=False,
                        help="Follow the comic's first-page link before walking.")
    params.add_argument("--limit", type=int, default=0, help="Stop the walk after this many pages.")
    params.add_argument("--root", default=None, help="Library folder, used to name the cache.")
    params.add_argument("--dry-run", "-n", action='store_true', default=False,
                        help="With refetch, say what would be fetched and change nothing.")
    params.add_argument("--all", action='store_true', default=False,
                        help="With refetch, fetch every page again, not only those that differ.")
    params.add_argument("--repack", action='store_true', default=False,
                        help="With refetch, write the .cbz afresh afterwards so it holds the new copies.")
    params.add_argument("--cbz", default=None, help="The archive to repack, when the metadata does not say.")
    params.add_argument("--cbz-folder", default=None,
                        help="With pack, where the chapter archives go. Defaults to the comic's own folder "
                             "inside the archive shelf.")
    params.add_argument("--replace", action='store_true', default=False,
                        help="With pack, remove the single archive once every page is checked to be in a "
                             "chapter archive, and stop scrapes rebuilding it.")
    params.add_argument("--archive", default=None,
                        help="With chapters, the comic's archive page, which is read for chapter headings.")
    params.add_argument("--list", default=None,
                        help="With chapters, a file of chapter start addresses, one per line, each "
                             "optionally followed by | and a title.")
    params.add_argument("--urls", action='store_true', default=False,
                        help="With chapters, work them out from the comic's own addresses, even when it "
                             "remembers an archive page.")
    params.add_argument("--browser", action='store_true', default=False,
                        help="With chapters, load the archive page in the browser, for a page that builds "
                             "itself with javascript.")
    params.add_argument("--shift", type=int, default=0,
                        help="With chapters, move every boundary this many pages, for an archive that "
                             "labels a chapter after its first page rather than before it.")
    params.add_argument("--force", action='store_true', default=False,
                        help="With chapters and --save, take a change that moves chapters which already "
                             "have archives, not only one that adds chapters at the end.")
    params.add_argument("--save", action='store_true', default=False,
                        help="With chapters, write what it worked out into the comic's metadata.")
    params.add_argument("--url", default=None,
                        help="With insert, the address of the page to put in.")
    params.add_argument("--after", default=None,
                        help="With insert, the page it follows: its address or its number.")
    params.add_argument("--json", action='store_true', default=False,
                        help="With show, print every page as JSON, for a page picker to offer.")
    params.add_argument("--file", default=None,
                        help="With recovered, the filename of the page you put there by hand.")
    params.add_argument("--note", default=None,
                        help="With recovered, where it came from, kept with it in the metadata.")
    params.add_argument("--no-repack", action='store_true', default=False,
                        help="With fix, leave the chapter archives alone, even where the correction "
                             "changed what belongs in one.")
    params.add_argument("--page", default=None,
                        help="With refetch, only these pages, by number: --page 1 or --page 1,5,9.")
    params.add_argument("--as-named", action='store_true', default=False,
                        help="With refetch, save each page under the name the site's image has now and "
                             "remove the file that was there, for a page whose saved file is not its "
                             "image at all.")
    params.add_argument("--by-time", action='store_true', default=False,
                        help="With align, line the pages up by the order their files were written, for a "
                             "comic this scraper downloaded in one pass without numbering them.")
    params.add_argument("--at", default=None,
                        help="With fix, the page the correction is about: its address, or its page number.")
    params.add_argument("--label", default=None,
                        help="With fix, what the chapter starting at that page is called. Naming a chapter "
                             "that is already there moves it to this page rather than adding another.")
    params.add_argument("--drop", action='store_true', default=False,
                        help="With fix, no chapter starts at that page, whatever the archive or the "
                             "addresses say.")
    params.add_argument("--forget", action='store_true', default=False,
                        help="With fix, take back the correction made about that page.")
    params.add_argument("--clear", action='store_true', default=False,
                        help="With fix, take back every correction made about this comic.")
    params.add_argument("--script", default=None, help="Path to mirror_base.py.")
    params.add_argument("--like", default=None,
                        help="With try, one of the comic's page addresses, when its folder does not say.")
    params.add_argument("--cache", default=None,
                        help="The walk's cache file, when it is not the one in the config folder.")
    return params.parse_args()


def main():
    args = setup()
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder) and not (args.what == "try" and args.like):
        print("ERROR: {0} is not a folder.".format(folder))
        return 2
    if args.what == "show":
        path = index_path(folder, args.root, args).replace(".jsonl", ".align.json")
        if not os.path.exists(path):
            print("ERROR: {0} has not been lined up yet.".format(folder))
            return 2
        saved = json.load(open(path, encoding='utf-8'))
        if args.json:
            #every page, for something that wants to offer them to choose from rather than read them
            json.dump({"comic": saved["comic"], "settled": saved.get("settled"),
                       "pages": [{"n": page["n"], "url": page["url"], "title": page.get("title"),
                                  "file": page.get("file")} for page in saved["pages"]]},
                      sys.stdout)
            return 0
        print("{0}: {1} pages, {2}".format(saved["comic"], len(saved["pages"]),
                                           "settled" if saved["settled"] else "NOT settled"))
        for page in saved["pages"][:5] + saved["pages"][-5:]:
            print("  {0:>5}  {1:<28} {2:<6} {3}".format(page["n"], str(page["file"])[:28], page["how"] or "-",
                                                        page["url"]))
        return 0
    if args.what == "try":
        if not args.archive:
            print("ERROR: say which page to read, with --archive.")
            return 2
        return try_archive(folder, args)
    if args.what == "pack":
        return pack(folder, args)
    if args.what == "chapters":
        return plan(folder, args)
    if args.what == "fix":
        return edit_fixes(folder, args)
    if args.what == "renumber":
        return renumber(folder, args)
    if args.what == "recovered":
        return mark_recovered(folder, args)
    if args.what == "insert":
        return insert_page(folder, args)
    if args.what == "refetch":
        return refetch(folder, args)
    if args.what == "repack":
        return repack(folder, args)
    if args.what == "index":
        if walk(folder, args) is None:
            return 2
    return do_align(folder, args)


if __name__ == "__main__":
    sys.exit(main())
