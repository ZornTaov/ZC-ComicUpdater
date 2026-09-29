#chapters worked out from the comic's own addresses - /c4/p7, /comic/issue-4-page-7 - or from a list of the
#addresses each chapter starts at.
import collections
import re

from comiclib.chapters.links import same_page


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
        #a short tag before the number is a site's shorthand for the comic itself - /mc/12-1 is My Comic
        #chapter 12 - and naming the chapter after the comic says nothing
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
    #a comic whose addresses carry the chapter: /c4/p7, /mc/4-7, /comic/issue-4-page-7. every number in
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
