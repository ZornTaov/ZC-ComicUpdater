#ComicInfo.xml, which a reader looks in to know what an archive is: the series, which part of it, how many
#pages, and the shape of each. written to the v2.1 draft of the anansi project's schema, whose elements are a
#sequence - a strict reader refuses them out of order - so they go in the schema's order whatever order they
#are thought of in here.
import os
import re
import struct
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from comiclib.metadata import read as read_metadata

NAME = "ComicInfo.xml"
#what a reader's list of formats calls a comic published on the web
FORMAT = "Web Comic"
#a page this much wider than it is tall is two pages drawn as one, which a reader shows alone in a spread
SPREAD = 1.2
#most pictures say their size in their first few bytes. a jpeg carrying a thumbnail of itself in its exif
#says it after the thumbnail, so one that has not said by then is read further, once
HEAD, LONG_HEAD = 4096, 262144
#what xml 1.0 cannot carry at all, even escaped. a label scraped from a page can hold anything
UNWRITABLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#the start of every frame marker that says a jpeg's size: every SOF but the three that are something else
JPEG_FRAMES = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
#every element of the schema, in its order, with the name each goes by here where this works one out. the
#rest are only ever written as another program's ComicInfo said them
SCHEMA = (("Title", "title"), ("Series", "series"), ("Number", "number"), ("Count", "count"),
          ("Volume", None), ("AlternateSeries", None), ("AlternateNumber", None), ("AlternateCount", None),
          ("Summary", "summary"), ("Notes", "notes"), ("Year", "year"), ("Month", None), ("Day", None),
          ("Writer", "writer"), ("Penciller", "penciller"), ("Inker", None), ("Colorist", None),
          ("Letterer", None), ("CoverArtist", None), ("Editor", None), ("Translator", None),
          ("Publisher", None), ("Imprint", None), ("Genre", "genre"), ("Tags", "tags"), ("Web", "web"),
          ("PageCount", None), ("LanguageISO", None), ("Format", None), ("BlackAndWhite", None),
          ("Manga", None), ("Characters", None), ("Teams", None), ("Locations", None),
          ("ScanInformation", None), ("StoryArc", None), ("StoryArcNumber", None), ("SeriesGroup", None),
          ("AgeRating", None), ("Pages", None), ("CommunityRating", None), ("MainCharacterOrTeam", None),
          ("Review", None), ("GTIN", None))
#what another program's ComicInfo is never believed about: the pages are this archive's own, named and
#sized and stood in for here, and Count tells a reader the series is complete, which only the reader may say
NEVER_KEPT = ("Pages", "PageCount", "Count")


def dimensions(head):
    #a picture's (width, height) from its first bytes, or None when they do not say - not a picture, a
    #kind with no size up front, or a jpeg that says it further in
    try:
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            return webp_dimensions(head)
        if head.startswith(b"BM"):
            if struct.unpack("<I", head[14:18])[0] == 12:
                return struct.unpack("<HH", head[18:22])
            width, height = struct.unpack("<ii", head[18:26])
            #a bitmap stored top row first says so with a negative height
            return width, abs(height)
        if head.startswith(b"\xff\xd8"):
            return jpeg_dimensions(head)
    except struct.error:
        #cut off before the size: a file still being written, or not what its first bytes claim
        return None
    return None


def webp_dimensions(head):
    kind = head[12:16]
    if kind == b"VP8 ":
        width, height = struct.unpack("<HH", head[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if kind == b"VP8L":
        b = head[21:25]
        if len(b) < 4:
            return None
        return 1 + (b[0] | (b[1] & 0x3F) << 8), 1 + (b[1] >> 6 | b[2] << 2 | (b[3] & 0x0F) << 10)
    if kind == b"VP8X":
        if len(head) < 30:
            return None
        return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
    return None


def jpeg_dimensions(head):
    at = 2
    while at + 9 <= len(head):
        if head[at] != 0xFF:
            return None
        marker = head[at + 1]
        if marker == 0xFF:
            #padding between markers
            at += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            #the markers that carry nothing after them
            at += 2
            continue
        if marker in JPEG_FRAMES:
            height, width = struct.unpack(">HH", head[at + 5:at + 9])
            return width, height
        at += 2 + struct.unpack(">H", head[at + 2:at + 4])[0]
    return None


def measure(read):
    #(width, height) of a picture, given read(n) for its first n bytes; None when it does not say
    head = read(HEAD)
    found = dimensions(head)
    if found is None and head.startswith(b"\xff\xd8") and len(head) >= HEAD:
        found = dimensions(read(LONG_HEAD))
    return found


def page(size, shape, standin):
    #what ComicInfo says of one page
    return {"size": size, "width": shape[0] if shape else None, "height": shape[1] if shape else None,
            "standin": bool(standin)}


#what someone may say about a comic themselves, kept in its metadata as "info" and written into every
#archive it has, by the names this works them out under
INFO = ("title", "series", "summary", "year", "writer", "penciller", "genre", "tags", "web")
#the rest of the schema that may be said by hand as well, kept in the same block by its ComicInfo name, as
#a publisher or a reading direction is. what tells one archive of a comic from the next - its number, how
#many there are, its notes - and what describes its pages is worked out, never said
EXTRA = tuple(tag for tag, key in SCHEMA if key is None and tag not in ("Pages", "PageCount"))
#what each is called on a form; a tag left out is its own name split into words
LABELS = {"title": "Title", "series": "Series", "summary": "Summary", "year": "Year", "writer": "Writer",
          "penciller": "Artist", "genre": "Genre", "tags": "Tags", "web": "Web address",
          "LanguageISO": "Language (ISO code)", "Manga": "Manga (reading direction)", "GTIN": "GTIN (ISBN)",
          "MainCharacterOrTeam": "Main character or team"}
#the order a form shows the nine in: who and when beside what, and the summary, the long one, last
SHOWN = ("title", "series", "writer", "penciller", "year", "genre", "tags", "web", "summary")
#given a box of their own rather than a line
LONG = ("summary", "Review")
#a whole number in the schema: a strict reader refuses an archive saying anything else
NUMBERS = ("year", "Volume", "AlternateCount", "Month", "Day")
#the schema's lists of what may be said, offered as they are spelled there
CHOICES = {"BlackAndWhite": ["Unknown", "No", "Yes"],
           "Manga": ["Unknown", "No", "Yes", "YesAndRightToLeft"],
           "AgeRating": ["Unknown", "Adults Only 18+", "Early Childhood", "Everyone", "Everyone 10+", "G",
                         "Kids to Adults", "M", "MA15+", "Mature 17+", "PG", "R18+", "Rating Pending", "Teen",
                         "X18+"]}


def label(key):
    return LABELS.get(key) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).capitalize()


def form():
    #what an editor of these offers, for a page to draw: the nine every comic is asked about, and the rest
    #of the schema to add one at a time. each as [name, label, long]
    return {"fields": [[key, label(key), key in LONG] for key in SHOWN],
            "extra": [[tag, label(tag), tag in LONG] for tag in EXTRA],
            "numbers": list(NUMBERS), "choices": CHOICES}


def fit(key, value):
    #a value as a ComicInfo may carry it, or None for one it cannot: a number that is not one, a choice
    #that is not on the schema's list, a rating outside nought to five
    value = UNWRITABLE.sub("", str(value)).strip()
    if not value:
        return None
    if key in NUMBERS:
        return int(value) if value.isdigit() else None
    if key in CHOICES:
        return next((choice for choice in CHOICES[key] if choice.lower() == value.lower()), None)
    if key == "CommunityRating":
        try:
            rating = float(value)
        except ValueError:
            return None
        return value if 0 <= rating <= 5 else None
    return value


def unsayable(info):
    #what was given that cannot be kept, as what to do about each, so a typo is said rather than dropped
    out = []
    for key, value in (info or {}).items():
        if (key in INFO or key in EXTRA) and value is not None and str(value).strip() and fit(key, value) is None:
            out.append("{0} has to be {1}".format(label(key), "a whole number" if key in NUMBERS
                                                  else "a number from 0 to 5" if key == "CommunityRating"
                                                  else "one of " + ", ".join(CHOICES.get(key, []))))
    return out


def clean_info(info):
    #an info block as it is kept: only what is known, as text, with nothing said left out. a year is a
    #number, since a reader sorts by it; one that is not is not kept
    out = {}
    for key in INFO + EXTRA:
        value = (info or {}).get(key)
        if value is None:
            continue
        value = fit(key, value)
        if value is not None:
            out[key] = value
    return out


def with_said(about, info, own=()):
    #what was said by hand, over everything else: the nine by the names they are worked out under, the rest
    #of the schema among the kept tags, which build writes in their places. own is what belongs to the
    #archive rather than the comic - a chapter's title and address - and is left as it is
    about = dict(about)
    kept = dict(about.get("kept") or {})
    for key, value in clean_info(info).items():
        if key in own:
            continue
        if key in INFO:
            about[key] = value
        else:
            kept[key] = value
    if kept:
        about["kept"] = kept
    return about


def said_in(body):
    #what a ComicInfo says that could be said by hand, by the info block's names: what an editor starts
    #from, and what tells whether a folder of archives all say the same. {} for anything that is not one
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError, TypeError):
        return {}
    names = dict((tag, key) for tag, key in SCHEMA if key in INFO)
    said = {}
    for element in root:
        tag = element.tag.split('}')[-1] if isinstance(element.tag, str) else None
        key = names.get(tag) or (tag if tag in EXTRA else None)
        text = UNWRITABLE.sub("", element.text or "").strip()
        if key and text and len(element) == 0:
            said.setdefault(key, text)
    return said


def said_by(about):
    #what an archive made from this about says, the same way: read back from what would be written, so it
    #is exactly that - Format's own default among it
    return said_in(build(about, []))


def retold(body, changes):
    #another program's ComicInfo with what was changed by hand changed in it, and nothing else. each change
    #is by the info block's names, None taking a tag out; a new element goes where the schema's sequence
    #puts it, since a strict reader holds an archive to that. None for a ComicInfo that cannot be read
    try:
        root = ET.fromstring(body) if body else ET.Element("ComicInfo")
    except (ET.ParseError, ValueError, TypeError):
        return None
    order = [tag for tag, _ in SCHEMA]
    tags = dict((key, tag) for tag, key in SCHEMA if key)
    for key, value in changes.items():
        tag = tags.get(key, key)
        found = root.find(tag)
        if value is None:
            if found is not None:
                root.remove(found)
            continue
        if found is None:
            found = ET.Element(tag)
            rank = order.index(tag)
            at = next((n for n, child in enumerate(root)
                       if child.tag in order and order.index(child.tag) > rank), len(root))
            root.insert(at, found)
        found.text = str(value)
    ET.indent(root, "  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def about_comic(folder, metadata=None):
    #what an archive holding the whole comic says it is: the series, and the site it is mirrored from. the
    #site, not the page it was last read up to, so the ComicInfo does not change every time the comic does.
    #what was said about it by hand says otherwise wherever it says anything
    if metadata is None:
        metadata = read_metadata(folder)
    series = os.path.basename(os.path.abspath(folder))
    #the project's name from before ZornCoMix, kept: a ComicInfo saying anything new is appended to every
    #archive on the next update, and a library's worth of those is no price for a name in a note
    about = {"title": series, "series": series, "web": site((metadata.get("settings") or {}).get("url")),
             "notes": "Mirrored by ZC-ComicUpdater."}
    about = with_kept(about, metadata.get("comicinfo"))
    return with_said(about, metadata.get("info"))


def about_chapter(folder, metadata, chapter, count):
    #what one chapter's archive says it is. how many chapters there are is said only once the reader has
    #said the comic has ended: a reader takes Count as the series being complete, and a comic still running
    #has no last chapter yet. what was said about the comic by hand is said of each chapter, but for the
    #chapter's own title and address: those are the chapter's, not the comic's
    series = os.path.basename(os.path.abspath(folder))
    ended = bool((metadata.get("settings") or {}).get("ended"))
    #the chapter's own number where its label says one (numbering.numbered), else its place in the comic
    about = {"title": chapter["label"], "series": series, "number": chapter.get("called") or chapter["number"],
             "count": count if ended else None, "web": chapter.get("start_url"),
             "notes": "Mirrored by ZC-ComicUpdater, pages {0} to {1} of the comic.".format(
                 chapter["start_page"], chapter["end_page"]),
             "bookmark": chapter["label"]}
    #what another program said of the whole comic is said of each chapter too, but for what names one
    #part of it; what it said of this chapter is said in full
    comic_wide = {tag: text for tag, text in (metadata.get("comicinfo") or {}).items()
                  if tag not in ("Title", "Number", "Web")}
    about = with_kept(about, dict(comic_wide, **(chapter.get("comicinfo") or {})))
    info = clean_info(metadata.get("info"))
    about = with_said(about, info, own=("title", "web"))
    if not about.get("web"):
        about["web"] = info.get("web")
    return about


def kept_tags(body):
    #another program's ComicInfo, as what it says: each plain element by its tag, in the order it came. read
    #so a comic taken from that program says everything it did - its publisher, its reading direction, a
    #chapter's real number - and not only what this works out. {} for anything that is not a ComicInfo
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError, TypeError):
        return {}
    kept = {}
    for element in root:
        #a namespace some writers add says nothing a reader goes by
        tag = element.tag.split('}')[-1] if isinstance(element.tag, str) else None
        text = UNWRITABLE.sub("", element.text or "").strip()
        if tag and text and len(element) == 0 and tag not in NEVER_KEPT:
            kept.setdefault(tag, text)
    return kept


def with_kept(about, kept):
    #what another program said, over what was worked out here: it may know a chapter's real number, or a
    #title better than a folder's name. what is said by hand is laid over both afterwards by the caller.
    #notes say both, theirs first, since what it noted is about the comic and what this notes is about itself
    if not kept:
        return about
    about = dict(about)
    ours = dict((tag, key) for tag, key in SCHEMA if key)
    for tag, text in kept.items():
        key = ours.get(tag)
        if key == "notes" and about.get("notes"):
            about["notes"] = text + "\n" + about["notes"]
        elif key:
            about[key] = text
        else:
            about.setdefault("kept", {})[tag] = text
    return about


def site(url):
    #the front page of the site an address is on
    found = re.match(r"^(https?://[^/?#]+)", url or "")
    return found.group(1) + "/" if found else None


def build(about, pages):
    #the ComicInfo.xml for an archive, as bytes. pages are the archive's pages in reading order, each as
    #page() makes them. the same about and pages make the same bytes, so whether an archive's ComicInfo
    #needs writing again is a comparison
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']

    def field(tag, value):
        if value is not None and value != "":
            lines.append("  <{0}>{1}</{0}>".format(tag, escape(UNWRITABLE.sub("", str(value)))))

    kept = about.get("kept") or {}
    for tag, key in SCHEMA:
        if key:
            field(tag, about.get(key))
        elif tag == "PageCount":
            field(tag, len(pages))
        elif tag == "Format":
            field(tag, kept.get(tag) or FORMAT)
        elif tag == "Pages":
            if pages:
                lines.append("  <Pages>")
                for at, each in enumerate(pages):
                    lines.append("    <Page {0} />".format(" ".join(
                        "{0}={1}".format(key, quoteattr(UNWRITABLE.sub("", str(value))))
                        for key, value in page_attributes(at, each, about.get("bookmark")))))
                lines.append("  </Pages>")
        else:
            field(tag, kept.get(tag))
    #anything a newer schema has that this one does not still says what it said, after all it knows of
    known = set(tag for tag, _ in SCHEMA)
    for tag, text in kept.items():
        if tag not in known and re.match(r"^[A-Za-z_][\w.-]*$", tag):
            field(tag, text)
    lines.append("</ComicInfo>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def page_attributes(at, each, bookmark):
    #in the schema's order. a page is Story unless it says otherwise, so only the others are written
    width, height = each.get("width"), each.get("height")
    attributes = [("Image", at)]
    if each.get("standin"):
        #a page saying where a video or a flash page went: a reader can tell it is not a page of the story
        attributes.append(("Type", "Other"))
    elif at == 0:
        attributes.append(("Type", "FrontCover"))
    if width and height and width > height * SPREAD:
        attributes.append(("DoublePage", "true"))
    attributes.append(("ImageSize", each["size"]))
    if at == 0 and bookmark:
        attributes.append(("Bookmark", bookmark))
    if width and height:
        attributes += [("ImageWidth", width), ("ImageHeight", height)]
    return attributes


def pages_said(text):
    #what a ComicInfo says of each page, in order, as page() makes them. empty when it says nothing that
    #can be read, which leaves every page to be measured again
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    said = []
    for each in root.iter("Page"):
        try:
            size = int(each.get("ImageSize", ""))
        except ValueError:
            size = None
        try:
            shape = (int(each.get("ImageWidth")), int(each.get("ImageHeight")))
        except (TypeError, ValueError):
            shape = None
        said.append(page(size, shape, each.get("Type") == "Other"))
    return said
