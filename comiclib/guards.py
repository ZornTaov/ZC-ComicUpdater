#the checks a scrape makes before it writes a page: that the next link is not running backwards, that a
#page is not about to be written over a different one, and that one page does not end up held under two
#names. each is handed the run's state rather than keeping any of its own.
import os
import re

from comiclib.metadata import METADATA_FILE as metadata_file
from comiclib.pages import page_key


def reads_backwards(sits_at, came_from, scrape_state):
    #whether the comic has turned round, judged over more than one page. one step back is not evidence:
    #a site that numbers each chapter's pages from one - /comics/1/1.png, and later /comics/131/1.png -
    #hands back a name it has used before at every chapter boundary,
    #which looks backwards for exactly one page and then climbs again. a next link that really runs
    #backwards keeps running backwards.
    steps_back = sits_at is not None and came_from is not None and sits_at < came_from
    scrape_state["backwards_run"] = scrape_state["backwards_run"] + 1 if steps_back else 0
    return scrape_state["backwards_run"] > 1


def would_lose_a_page(target, prefix, saved_so_far, fresh):
    #a site that reuses one filename for a page of every chapter would, without a numbered prefix, write
    #each chapter over the last. the run would look like a success and only the page count would say
    #otherwise. a resume re-saves the page it starts on, which is why this only counts once past it.
    #
    #but a name already here is not enough to say a page would be lost: a comic reaches a page it already
    #holds all the time - a gap filled by hand, a run that overlaps the last one - and writing that page
    #over itself loses nothing. what a page is, is its bytes, so those are what decide.
    if prefix or saved_so_far <= 0 or not os.path.exists(target):
        return False
    try:
        with open(target, 'rb') as held:
            return held.read() != fresh
    except OSError:
        return False


def drop_superseded(folder, increment, keeping, superseded):
    #one page should own one filename. a resume re-saves the page it starts on, and if the name that
    #lands differs from the name already there - an extension appended twice, or a hand renumbering that
    #kept only the number - the folder would hold that page twice and every reader would show it twice.
    #the freshly named file wins, so the comparison never has to happen again for this comic. what is
    #dropped goes on `superseded`, so the archive can be told as well.
    try:
        present = os.listdir(folder)
    except OSError:
        return
    for name in present:
        if name in (keeping, metadata_file):
            continue
        #the leading number is what says which page a file is, however the rest of it is spelled:
        #'0743_a-page.png.png' and the hand renumbered '0743.png' are both page 743
        numbered = re.match(r'^(\d{3,})[_.]', name)
        if not numbered or int(numbered.group(1)) != int(increment):
            continue
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        try:
            os.remove(full)
        except OSError as error:
            print("WARNING: could not drop the older name {0}: {1}".format(name, error))
            continue
        superseded.append(name)
        print("Dropped {0}, superseded by {1}.".format(name, keeping))


def drop_other_spellings(folder, keeping, superseded):
    #the same for a comic whose pages carry no number: there, what says which page a file is, is the page
    #it names, however it was spelled. the page a resume starts on, saved before names were taken as the
    #site gives them, is a-page.jpg.png, and saved again now is a-page.jpg - one page, which a reader would
    #otherwise show twice. only ever asked about the page a resume starts on, which is the one page a run
    #knows it is saving again.
    try:
        present = os.listdir(folder)
    except OSError:
        return
    wanted = page_key(keeping)
    for name in present:
        if name in (keeping, metadata_file) or page_key(name) != wanted:
            continue
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        try:
            os.remove(full)
        except OSError as error:
            print("WARNING: could not drop the older name {0}: {1}".format(name, error))
            continue
        superseded.append(name)
        print("Dropped {0}, superseded by {1}.".format(name, keeping))
