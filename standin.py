"""Stand-in pages, for a page no reader can show.

A comic does not always give you a picture. A page can animate, and the only capture of it is a
recording; it can be a video the comic links to, noted beside the pages; it can have been Flash before
Flash went away. Those are pages of the comic and they belong in the folder - but an archive that held
only what a reader can open would leave them out, and they would read as gaps.

So the archive gets a page of its own in their place, saying what the page is and where the real thing
is. It is drawn here rather than by an image library: requirements.txt is deliberately selenium and
requests, and a page saying where a video went is not worth rebuilding the container over.

Both the single archive that mirror_base writes and the per-chapter ones that chapters.py writes use
this, so a page reads the same either way.
"""
import os
import re
import struct
import zlib

#a page can be held as something no reader can show: a recording of a page that animated, a flash file
#from before flash went away, or a note saying where the page lives now.
video_types = re.compile(r"\.(mp4|m4v|webm|mov|mkv)$", re.I)
flash_types = re.compile(r"\.swf$", re.I)
link_types = re.compile(r"\.(txt|url|webloc)$", re.I)
#not anchored: a note can run its own words straight into the address, which is what Wapsi Square does
a_web_address = re.compile(r"(https?://\S+)")
#a note about a page is named like a page - 4017.txt, beside 4016.png - which is what tells it from a
#comic's readme. a readme can mention all the addresses it likes; it is still not page 4017.
named_for_a_page = re.compile(r"^(\d+)(?:[._])")


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
    if link_types.search(name) and named_for_a_page.match(name):
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

