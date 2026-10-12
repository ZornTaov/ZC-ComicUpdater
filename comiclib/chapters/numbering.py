#a chapter's own number, read from its label - Chapter 391, Book #12, 12. Off to the Movies - for its
#archive's name and its ComicInfo. the chapter list's "number" is the chapter's place in the comic, which is
#only its real number for a comic kept from its first chapter with nothing in between. worked out from the
#labels every time it is asked, never stored, so the scraper and the reader cannot hold two answers.
#stdlib only: the reader imports this.
import re
from decimal import Decimal

#a number a label says it is: after a word that counts chapters, or opening the label. "part" is not one -
#a comic numbers the parts of each story from 1 again ("The Third Game (Part 3)", then "(Part 1)") - and
#a vulgar fraction ("5½") is a number this cannot write, so a label saying one says nothing
COUNTED = re.compile(r"\b(?:chapter|chap|ch|episode|ep|issue|book|arc|story)\b\s*\.?\s*#?\s*(\d+(?:\.\d+)?)(?![\d½¼¾])"
                     r"|#\s*(\d+(?:\.\d+)?)(?![\d½¼¾])", re.I)
OPENING = re.compile(r"^\s*(\d+(?:\.\d+)?)(?![\d½¼¾])")
#the steps numberless chapters take after the number before them: an intermission after 12 is 12.5, a
#second in a row 12.6. more in one run than this and the comic keeps plain places rather than invent more
HALF, STEP, MOST_IN_A_RUN = Decimal("0.5"), Decimal("0.1"), 5


def label_number(label):
    found = COUNTED.search(label or "") or OPENING.match(label or "")
    if not found:
        return None
    return Decimal(next(group for group in found.groups() if group))


def written(number):
    #a number as a person writes it: 12, 12.5, 0 - never 012, 12.50 or 1E+1
    return "{0:f}".format(Decimal(number).normalize())


def same(one, other):
    #two ways of writing one number, "012.5" and "12.5", or "010" and "10"
    try:
        return Decimal(str(one)) == Decimal(str(other))
    except ArithmeticError:
        return str(one) == str(other)


def places(chapters):
    return [written(chapter.get("number") or at) for at, chapter in enumerate(chapters, 1)]


def real_numbers(block):
    #each chapter's number, in the order of the list, as text. a comic whose labels do not say a number
    #that rises chapter by chapter keeps its plain places: a comic cut every so many pages, one whose
    #chapters are only titled, or one whose numbers go back and forth would otherwise be filed out of order
    chapters = (block or {}).get("list") or []
    if not chapters or (block or {}).get("source") == "every":
        return places(chapters)
    said = [label_number(chapter.get("label")) for chapter in chapters]
    known = [number for number in said if number is not None]
    if not known or any(later <= earlier for earlier, later in zip(known, known[1:])):
        return places(chapters)
    numbers = list(said)
    at = 0
    while at < len(numbers):
        if numbers[at] is not None:
            at += 1
            continue
        end = at
        while end < len(numbers) and numbers[end] is None:
            end += 1
        run = end - at
        after = numbers[end] if end < len(numbers) else None
        if run > MOST_IN_A_RUN:
            return places(chapters)
        if at == 0:
            #ahead of the first number: a prologue is 0, several lead-ins 0, 0.1, 0.2
            steps = [STEP * step for step in range(run)]
        else:
            steps = [numbers[at - 1] + HALF + STEP * step for step in range(run)]
        if after is not None and steps[-1] >= after:
            return places(chapters)
        numbers[at:end] = steps
        at = end
    return [written(number) for number in numbers]


def numbered(block):
    #the chapter list with each chapter's own number beside its place, as "called"
    chapters = (block or {}).get("list") or []
    return [dict(chapter, called=called) for chapter, called in zip(chapters, real_numbers(block))]


def name_part(called):
    #how a number goes in an archive's name: three digits before any fraction, so the names sort the way
    #the chapters read - c012, c012.5, c013
    whole, _, fraction = written(called).partition(".")
    return "{0:03d}{1}".format(int(whole), "." + fraction if fraction else "")
