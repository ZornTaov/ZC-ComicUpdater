#reading a comic's archive page for where its chapters start: headings, and the links under them, matched
#against the pages the walk recorded. what a heading looks like differs from site to site, so anything
#that could be one is kept and a link goes under whichever came last before it.
import html.parser
import re
import subprocess
import sys

import requests

from comiclib.chapters.index import MIRROR
from comiclib.chapters.links import link_targets, looks_like_pages, same_page


def drawn_heading(attrs):
    #a site that draws its chapter headings instead of writing them. one that heads each chapter with
    #<img src="chapter12.png"> and no words at all has the only name on the page in the picture - and
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
        #some archives are a dropdown rather than a list of links: every page of a comic as an <option>,
        #and a script that sends you to the value when you pick one. that is a link
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
        #not a heading: a whole chapter list wrapped in <div id="chapters">, and each chapter's table given
        #an id of chapter12_table, both read as headings by their names alone. given
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
        done = subprocess.run([sys.executable, script or MIRROR, "--page-source", url],
                              capture_output=True, text=True, timeout=300)
        return done.stdout
    answer = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    answer.raise_for_status()
    return answer.text


def heading_says(text):
    #an archive that says how long each chapter is: "3. A Day Out (4 pages, 5/8/06)". the count is
    #the site's own word on how many pages the chapter holds, which is something a reading can be checked
    #against, and it is not part of the chapter's name.
    found = re.search(r'\(\s*(\d+)\s*pages?\b[^)]*\)\s*$', text or "", re.I)
    if not found:
        return (text or "").strip(), None
    return text[:found.start()].strip().strip(',;:-').strip(), int(found.group(1))


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
