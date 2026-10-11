#reading a comic's archive page for where its chapters start: headings, and the links under them, matched
#against the pages the walk recorded. what a heading looks like differs from site to site, so anything
#that could be one is kept and a link goes under whichever came last before it.
import html.parser
import re
import subprocess
import sys
import urllib.parse

import requests

from comiclib.chapters.index import MIRROR
from comiclib.chapters.links import link_targets, looks_like_pages, page_shape, same_page

#the words a site calls its chapters by. a comic told as a few long stories, each a run of short storylines,
#heads them "Story 1", "Story 2" - and the storylines are only words in each page's title
chapter_words = r'(chapters?|chap|arcs?|volumes?|vol|books?|parts?|episodes?|seasons?|stor(?:y|ies))'


def names_a_chapter(text):
    #a link whose own words are a chapter's name: "Chapter 2: The Long Way Round", "Book #3". an archive
    #that writes its chapter names only as links - to a page listing that chapter, or to its first page -
    #has no heading anywhere else to name it by. the number has to be there, or "Chapters" in a menu would
    #be one, and a page of a chapter ("Chapter 3 Page 4") is a page, not a name
    if not re.match(chapter_words + r'\s*[-_.#:]?\s*(no\.?\s*)?#?\d', (text or "").strip(), re.I):
        return False
    return not re.search(r'\b(pages?|pg)\.?\s*#?\d', text, re.I)


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
    if not re.match('^' + chapter_words + r'\s*[-_.]?\s*(\d|$)', text, re.I):
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
        #how many tags like the heading's own are open inside it, so a <div> heading ends at its own
        #</div> and not at the first one inside it - which on a storyline's box is the first page's row,
        #and made that page's date the name of a chapter one page long
        self.depth = 0
        #whether the heading's class says it is the name of a chapter, not just somewhere near one
        self.named = False
        self.rank = 1
        self.said = []
        #what the heading says in its own right, with the words of the links inside it left out. a real
        #heading is usually one or the other, and telling them apart is what saves a container full of
        #links from reading as a heading whose name is every link in it, run together
        self.said_alone = []
        self.inside = []
        self.link = None
        self.link_text = []
        #the pictures inside the heading being read: a chapter's banner, drawn beside its name
        self.pictures = []

    def picture(self, src, how):
        #a picture that may be a chapter's banner, given out as an event of its own: "heading" for one that
        #belongs to the heading given out next, "link" for a thumbnail linked on its own, which is a
        #chapter's only if a heading follows it before any page does
        if src and not src.startswith("data:"):
            self.events.append(("image", src, how))

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
                #ranked below a written heading, so a site that has both is named by its words. the picture
                #is the chapter's banner as well as its name
                self.picture(got.get("src"), "heading")
                self.events.append(("heading", drawn, 1))
            elif self.heading:
                #inside a box that may yet turn out to be a storyline's: its thumbnail, kept with it
                self.pictures.append(got.get("src"))
            elif self.link is not None:
                self.picture(got.get("src"), "link")
            return
        if tag == "img":
            #a picture inside a written heading: the banner beside the chapter's name
            self.pictures.append(got.get("src"))
            return
        #whole words only: a class called comic-archive-date holds "arc" inside "archive" and is a date,
        #not a heading
        words = set(re.split(r'[^a-z]+', "{0} {1}".format(got.get("class") or "", got.get("id") or "").lower()))
        looks_like = tag in self.heading_tags or bool(
            words & {"chapter", "chapters", "arc", "arcs", "volume", "book", "story", "storyline"})
        #a box per storyline - its thumbnail, its name, its list of pages - is named for the storyline, and
        #so is the header inside it. the header is the one that says the name: the box only holds it
        names = looks_like and bool(words & {"header", "heading", "title", "name"})
        if (names and self.heading and not self.named and self.heading not in self.title_tags
                and tag not in self.title_tags):
            self.stop_holding()
        #the outermost heading wins, so a <b> inside an <h4> is emphasis in a title rather than a title of
        #its own - except that a real heading tag beats a container whose class merely says "chapter",
        #since such a container holds the description and the icon too, and none of that is a name
        if looks_like and (not self.heading
                           or (tag in self.title_tags and self.heading not in self.title_tags)):
            if not self.heading:
                self.inside = []
            self.heading = tag
            self.depth = 0
            self.named = names
            self.rank = 0 if tag in self.title_tags else 1
            self.said = []
        elif self.heading and tag == self.heading:
            self.depth += 1

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
            for src in self.pictures[:1]:
                self.picture(src, "heading")
            self.events.append(("heading", said, self.rank))
        else:
            #a storyline's box giving way to the header inside it: its thumbnail is the storyline's, if a
            #heading comes before any page does
            for src in self.pictures[:1]:
                self.picture(src, "link")
        for href, text in self.inside:
            self.give_link(href, text)
        self.heading = None
        self.depth = 0
        self.named = False
        self.said = []
        self.said_alone = []
        self.inside = []
        self.pictures = []

    def give_link(self, href, said):
        if names_a_chapter(said):
            #a link named for its chapter is that chapter's heading as well as a link. given out on its
            #own too, so a link to a page listing the chapter - not a page of the comic - still names the
            #first page of the comic that comes after it
            self.events.append(("heading", said, 0))
            self.events.append(("owned", href, said))
            return
        self.events.append(("link", href, said))

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
            self.give_link(self.link, said)
            self.link = None
            self.link_text = []
            return
        if self.heading and tag == self.heading and self.depth:
            self.depth -= 1
            return
        if self.heading and tag == self.heading:
            said = re.sub(r'\s+', ' ', "".join(self.said)).strip()
            if not re.search(r'[^\W_]', said):
                #punctuation and the separators between links are not a name
                said = ""
            if said:
                for src in self.pictures[:1]:
                    self.picture(src, "heading")
                self.events.append(("heading", said, self.rank))
            for href, text in self.inside:
                #a heading that holds the link names that chapter and nothing else does, whatever else
                #sits above it on the page. the heading is still given out on its own as well, so if this
                #link turns out not to be a page of the comic it can still name the next one that is.
                if said:
                    self.events.append(("owned", href, said))
                else:
                    self.give_link(href, text)
            self.heading = None
            self.depth = 0
            self.named = False
            self.said = []
            self.said_alone = []
            self.inside = []
            self.pictures = []

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
    links = []
    shape = page_shape(known)

    def fits(where):
        return re.match(shape, same_page(where).partition('?')[0])

    for kind, first, second in events:
        if kind not in ("link", "owned"):
            continue
        where = next((one for one in link_targets(base, first) if looks_like_pages(one, known)), None)
        if where is None or (names_a_chapter(second) and not fits(where)):
            #a chapter's name linking to the page that lists the chapter, in the same folder as the comic's
            #pages but not shaped like one: Arch_002.php beside Vol_007.php. a walked comic never counts it,
            #since the walk never goes there
            continue
        links.append(where)
    #with those gone, an archive whose pages are mostly one shape says what its pages look like, and the
    #few left that are not - the bonus section's own page, the wallpapers' - are pages about the comic. an
    #archive listing only where each chapter starts and ends has few pages to outnumber them by, so mostly
    #is four in five. only a reading with no walk to go on uses this: a walk says which pages there are
    shaped = [one for one in links if fits(one)]
    if len(shaped) >= len(links) * 0.8:
        links = shaped
    kept, order = [], {}
    for where in links:
        if same_page(where) not in order:
            kept.append(where)
            order[same_page(where)] = len(order) + 1
    return kept, order


def beside_its_heading(events):
    #a storyline's thumbnail links where its name does, and comes before the name. read as it stands it is
    #the last page of the chapter before, and a chapter that reaches into the next one's first page. the
    #name's own link says the same and says it with a name, so the picture's is let go
    kept = []
    for at, (kind, first, second) in enumerate(events):
        if kind == "link":
            after = next((event for event in events[at + 1:] if event[0] not in ("heading", "image")), None)
            if after is not None and after[0] in ("link", "owned") and same_page(after[1]) == same_page(first):
                continue
        kept.append((kind, first, second))
    return kept


def walked_at(where, base, href):
    #which page of the walk a link is, or None for a link to anything else
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    for one in link_targets(base, href):
        key = same_page(one)
        #a site's front page shows whichever page is newest, so it is never a page of its own - even when a
        #walk ended by stepping onto it - and every "home" link beside a heading would otherwise say that
        #heading lists a page
        if key.partition('/')[2] and key in where:
            return where[key]
    return None


def through_chapter_pages(events, where, base, fetch):
    #an archive that lists its chapters but none of their pages: each heading links only to a page of the
    #site's own listing that chapter's pages. that page is read for them, and the chapter starts at the
    #earliest of them in reading order - so a sidebar link to the newest page, on every page of the site,
    #never decides anything. a chapter page can run to several pages of its own, but the earliest are on
    #the first, whichever way round it lists them, unless it lists newest first across several
    site = same_page(base).partition('/')[0]
    groups, current = [], None
    for at, (kind, first, second) in enumerate(events):
        if kind == "heading":
            current = {"heading": at, "name": first, "links": []}
            groups.append(current)
        elif current is not None and kind != "image":
            current["links"].append((first, second))

    def target(href):
        return same_page(link_targets(base, href)[0]) if href else ""

    #a chapter's thumbnail links where its name does but comes before it, at the foot of the heading above.
    #a link at the end of one heading's lot that the next heading links to as well belongs to the next
    for this, after in zip(groups, groups[1:]):
        theirs = {target(href) for href, _ in after["links"]}
        while this["links"] and target(this["links"][-1][0]) in theirs:
            after["links"].insert(0, this["links"].pop())
    #any page the walk went to, to tell an address shaped like the comic's pages from one that is not
    known = min(where, key=where.get) if where else ""
    for group in groups:
        group["follow"] = None
        if any(walked_at(where, base, href) is not None for href, _ in group["links"]):
            continue
        #the one place on this site the heading leads, other than its front page or this archive. a
        #heading over several - the site's menu, a list of posts - is not a chapter's, and is left alone.
        #compared as same_page has them, but fetched as written: a path can care about its case
        others, paged = {}, False
        for href, _ in group["links"]:
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            address = link_targets(base, href)[0]
            there = same_page(address)
            if there.partition('/')[0] != site or not there.partition('/')[2] or there == same_page(base):
                continue
            #shaped like a page of the comic but never walked: a story told off the main run of next
            #links. it is not a list of anything, and reading it would find only its own buttons - the
            #first-page one among them, which would start the chapter at page 1
            if looks_like_pages(address, known):
                paged = True
                continue
            #the comic's own front page - /comic beside /comic/some-page - shows the newest page, and
            #reading it finds the same buttons
            if there.partition('/')[2] == same_page(known).partition('/')[2].split('/')[0]:
                continue
            others.setdefault(there, address)
        if len(others) == 1 and not paged:
            group["follow"] = next(iter(others.values()))
    wanted = [group for group in groups if group["follow"]]
    if not wanted:
        return events
    print("  reading {0} chapter page(s) for where each chapter starts ...".format(len(wanted)), flush=True)
    lists = {}
    for at, group in enumerate(wanted, 1):
        url = group["follow"]
        try:
            reader = ArchiveReader()
            reader.feed(fetch(url))
        except Exception as error:
            print("    could not read {0}: {1}".format(url, error))
            continue
        found = {}
        for kind, href, _ in reader.events:
            n = walked_at(where, url, href) if kind in ("link", "owned") else None
            if n is not None:
                found.setdefault(n, link_targets(url, href)[0])
        if found:
            lists[group["heading"]] = found
        if at % 10 == 0:
            print("    read {0} of {1}".format(at, len(wanted)), flush=True)
    #what every chapter page links - the newest page in a sidebar, the first in a header - is the site's
    #and says nothing about any one chapter
    common = set.intersection(*(set(found) for found in lists.values())) if len(lists) > 2 else set()
    own = {heading: sorted(set(found) - common) for heading, found in lists.items()}
    own = {heading: pages for heading, pages in own.items() if pages}
    #a page whose pages reach across other chapters' is not a chapter's at all but a list gathered from
    #across the comic - specials, one-shots - each of which stays where it was published. a chapter's pages
    #can have one of those inside them too, so the list reaching across the most is let go first, and then
    #the rest counted again, until no chapter's pages reach across another's
    gathered = set()
    while True:
        left = {heading: pages for heading, pages in own.items() if heading not in gathered}
        across = {heading: sum(1 for other, theirs in left.items() if other != heading
                               for n in theirs if pages[0] < n < pages[-1])
                  for heading, pages in left.items()}
        worst = max(across, key=across.get, default=None)
        if worst is None or not across[worst]:
            break
        gathered.add(worst)
    for heading in sorted(gathered):
        print("    {0} lists pages from across the comic, so it is not a chapter".format(
            events[heading][1][:50]))
    starts = {heading: lists[heading][pages[0]] for heading, pages in own.items() if heading not in gathered}
    #given out just after its heading, as a link the heading owns: named by the heading it sits under,
    #whatever grander heading - the archive's own title - is waiting above it
    out = []
    for at, event in enumerate(events):
        out.append(event)
        if at in starts:
            out.append(("owned", starts[at], event[1]))
    return out


def owner_image(waiting, said):
    #the banner of the heading a link sat inside, which is the latest one saying what the link was named by
    return next((held[3] for held in reversed(waiting) if held[2] == said), None)


def chapters_from_events(events, where, base="", fetch=None, outer=False):
    #a chapter starts at the first page link after a heading. several headings can sit together - a title
    #and the summary underneath it - so the one that reads most like a title wins: a real heading tag
    #first, and the earliest of those. given a way to fetch a page, a heading leading only to a page of
    #its own about the chapter has that page read for where the chapter starts.
    #outer is for an archive that nests its chapters inside larger ones - books, volumes, years - and is
    #to be cut by those: a heading with another heading straight under it, before any link, is one of them,
    #and a chapter starts only where one does, the chapters under it adding their pages to it
    if fetch is not None:
        events = through_chapter_pages(events, where, base, fetch)
    events = beside_its_heading(events)
    found, waiting, listed = [], [], set()
    #the outer heading waiting for the first page under it, and its banner
    parent = parent_image = None
    #a chapter's banner: the picture inside or drawn as the heading, given out just before it, or a thumbnail
    #linked on its own just above it - a storyline's box. a thumbnail with a page after it and no heading
    #between is that page's, in a gallery of every page, and no chapter's
    heading_image = loose_image = None
    #a section gathered from across the comic - fillers, omake, guest pages, listed apart under a heading of
    #their own - is not a chapter. its pages were published in among the chapters, and stay where they were
    #published, so a reader of the archives meets them exactly where a reader of the site does
    gathered, seen = False, set()
    for step, (kind, first, second) in enumerate(events):
        if kind == "image":
            src = urllib.parse.urljoin(base, first) if base else first
            if second == "heading":
                heading_image = src
            else:
                loose_image = src
            continue
        if kind == "heading":
            image, heading_image, loose_image = heading_image or loose_image, None, None
            #a picture between it and the heading under it is the next heading's banner, and stood aside
            after = next((event[0] for event in events[step + 1:] if event[0] != "image"), None)
            if outer and after == "heading":
                parent, parent_image = first, image
            waiting.append((second if second is not None else 1, len(waiting), first, image))
            continue
        owned = kind == "owned"
        at = walked_at(where, base, first)
        if at is None:
            continue
        loose_image = None
        #each page once, however often it is linked: a storyline's name and its first row both lead to its
        #first page, and counting both said an archive listed more pages than the comic has
        listed.add(at)
        already = next((chapter for chapter in found if chapter["start_page"] == at), None)
        if owned and already is not None:
            #this page already starts a chapter, named by whatever mentioned it first - often a dropdown
            #of every page under the archive's own banner. a heading built round this very link knows
            #better, so it renames that chapter rather than making a second one at the same page - or,
            #cutting by the outer headings, the one this page is the first of does
            if not outer:
                already["label"], already["pages_said"] = heading_says(second)
                already["image"] = already.get("image") or owner_image(waiting, second)
            elif parent is not None:
                already["label"], already["pages_said"] = heading_says(parent)
                already["image"] = already.get("image") or parent_image
                parent = parent_image = None
            waiting = []
            continue
        if outer and found and parent is None and (owned or waiting):
            #a chapter inside the outer one: its pages are the outer one's
            waiting = []
            owned = False
        if owned or waiting or not found:
            if at not in seen and any(min(chapter["pages_listed"]) < at < max(chapter["pages_listed"])
                                      for chapter in found if chapter["pages_listed"]):
                #it starts inside a chapter already read, at a page that chapter never listed, which no
                #chapter of a comic does: the pages under it are from all over, and each stays inside
                #whichever chapter it sits in. a page listed already is another matter - a dropdown of
                #every page, then the chapters' starts, names each start a second time
                gathered, waiting = True, []
                continue
            gathered = False
            #a heading that held this very link names it outright. otherwise the most heading-like wins,
            #and among equals the one nearest the link: a page's own banner sits far above the first
            #chapter's title, and a summary sits just under it
            best = min(waiting, key=lambda held: (held[0], -held[1])) if waiting else None
            label = (second if owned else best[2] if best else "Chapter {0}".format(len(found) + 1))
            #the banner of whichever heading named it
            image = owner_image(waiting, second) if owned else best[3] if best else None
            if outer and parent is not None:
                label, image, parent, parent_image = parent, parent_image, None, None
            label, says = heading_says(label)
            found.append({"label": label or "Chapter {0}".format(len(found) + 1),
                          "start_page": at, "pages_listed": [], "pages_said": says, "image": image})
            waiting = []
        elif gathered:
            continue
        seen.add(at)
        found[-1]["pages_listed"].append(at)
        found[-1]["start_page"] = min(found[-1]["start_page"], at)
    return found, len(listed)


def first_of_each(pages):
    #which page each address is. a page of several images is several lines with one address, and a chapter
    #starting there starts at its first image: taking the last would leave the others in the chapter before
    where = {}
    for page in pages:
        if page.get("url"):
            where.setdefault(same_page(page["url"]), page["n"])
    return where


def chapters_from_archive(url, pages, browser=False, script=None, outer=False):
    #the archive page says where each chapter starts; the walk says where every page sits. matching one
    #against the other needs no knowledge of the site beyond which links are pages of this comic.
    where = first_of_each(pages)
    reader = ArchiveReader()
    reader.feed(read_archive(url, browser, script))
    #plenty of archives link their pages relatively, so each is read against the archive's own address
    return chapters_from_events(reader.events, where, url,
                                fetch=lambda page: read_archive(page, browser, script), outer=outer)
