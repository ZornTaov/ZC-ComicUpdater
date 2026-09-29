#a small script to go through a webcomic and download all of the pages. #Written by AChillVamp. #V 3.9

import argparse
import json
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime
from time import sleep

import selenium.common.exceptions as se
from selenium.webdriver.common.by import By

#what this shares with the other scripts: where the settings are, what makes two filenames one page, the
#metadata file and how an archive is packed
from comiclib import browser, cbz, download, elements, exits, pagecheck, paths
from comiclib.metadata import METADATA_FILE, load, now_stamp, write_json
from comiclib.pages import held_pages, page_key, page_number, saved_name
from comiclib.standin import held_otherwise
from comiclib.paths import element_paths_file
#the scrape's own loop is this file; finding elements, pressing next and fetching an image are not, and
#are named here as they always were, so the loop reads the same and anything reaching in still finds them
from comiclib.browser import quit_quietly
from comiclib.download import fetch
from comiclib.elements import (comic_images, ele_get, ele_get_all, merge_paths, next_ele_get,  # noqa: F401
                               next_element, test_ele_get, test_next_ele_get)
from comiclib.exits import MirrorError

#global vars
custom_args = [
    ]

#the paths this script ships with, as AChillVamp's original had them: a starting point that fits plenty of
#comics, and nothing more. a library adds its own, puts them in a different order or turns one off without
#editing this file, by keeping an element_paths.json in its config folder - which is what the web page
#writes. anything the file does not mention keeps working, so a new entry shipped here later still arrives.
element_names = ['//*[@id="comic"]/a/img',
                 '//*[@class="comic"]',
                 '//*[@class="comic-wrap"]/img',
                 '//*[@alt="Comic"]',
                 '//*[@alt="comic"]',
                 '//*[@id="cc-comic"]',
                 '//*[@class="comic"]/img',
                 '//*[@class="ksc"]',
                 '//*[@id="main-comic"]',
                 '//*[@id="comicimage"]',
                 '//*[@id="last-path-for-happy-code"]',
                 "//img[@alt='post image']"]
next_ele_names = ['//*[@rel="next"]',
                  '//*[@alt="Next>"]',
                  '//*[@title="Next >"]',
                  '//*[@class="navi navi-next-in"]',
                  '//*[@class="navi comic-nav-next navi-next"]',
                  '//*[@alt="Next comic"]',
                  '//*[contains( text(), "Next")]',
                  '//*[contains( text(), "NEXT")]',
                  '//*[@src="next.jpg"]',
                  '//*[@alt="Next Page"]',
                  '//*[@id="Next_"]',
                  '//*[@class="nav-next "]',
                  '//*[@id="last-path-for-happy-code"]',
                  "//img[@alt='post image']"]


def load_element_paths():
    path = element_paths_file()
    if not os.path.exists(path):
        return
    global element_names, next_ele_names
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            saved = json.load(f)
        element_names = merge_paths(element_names, saved.get("image"))
        next_ele_names = merge_paths(next_ele_names, saved.get("next"))
    except (ValueError, OSError, AttributeError, TypeError) as error:
        #a broken file must not stop every comic in the library, so the built-in lists carry on alone
        print("WARNING: ignoring {0}: {1}".format(path, error))


load_element_paths()

#links back to the first page, used by --index when it is not told where a comic starts. only ever
#followed once, before the walk begins
first_ele_names = [
                   '//*[@rel="first"]',
                   '//*[@class="comic-nav-base comic-nav-first"]', #the ComicPress theme's
                   '//*[@class="navi navi-first"]',
                   '//*[@class="comic-nav-first"]',
                   '//*[@title="First"]',
                   '//*[@alt="First"]',
                   '//a[contains(translate(text(),"FIRST","first"), "first")]']

#what the page before this one showed, so an image that appears again can be told from a page of the
#comic. kept as the raw matches rather than what was kept of them, so furniture is recognised even on a
#page where it was already left out for another reason
last_page_url = None
last_page_srcs = set()
#how many pages of this run each image has turned up on. a button is on every page there is, while a
#picture the comic re-uses shows twice in the whole comic, which is what tells the two apart
seen_on_pages = {}
#the xpaths that matched this comic, cached so each page does not repeat the whole search. kept in their
#own variables rather than written back into the lists above, so a re-search still has every candidate.
image_xpath = None
next_xpath = None
current_url = None
verbose = False

#name of the sidecar written into the output folder, so it gets zipped into the cbz alongside the pages
metadata_file = METADATA_FILE
#how many run records to keep. a monthly updater would otherwise grow this file forever; the first run is
#always kept, since it is the one that says how the comic was originally scraped
max_runs = 20
arg_parser = None
run_start = None
#identifies this run in the metadata; a timestamp alone collides when a comic is scraped twice in one second
run_id = None
stop_reason = "incomplete"
#exit codes, so a batch driver can tell an ordinary update from a site that broke. the numbers live in
#comiclib.exits, beside what update_comics says about each
EXIT_OK = exits.OK
EXIT_INTERRUPTED = exits.INTERRUPTED
EXIT_USAGE = exits.USAGE
EXIT_NO_IMAGE = exits.NO_IMAGE
EXIT_DOWNLOAD = exits.DOWNLOAD
EXIT_DRIVER = exits.DRIVER
EXIT_TIMEOUT = exits.TIMEOUT
EXIT_UNEXPECTED = exits.UNEXPECTED
EXIT_BACKWARDS = exits.BACKWARDS
EXIT_SAME_NAMES = exits.SAME_NAMES

#how long to let one page load before giving up on it. selenium otherwise waits for the page to finish
#loading with no limit of its own, and the only thing that eventually breaks the wait is its internal
#http timeout, which surfaces as an unhandled error rather than something this script can report.
#a machine and network concern rather than a per-comic one, so it comes from the environment and stays
#out of the saved settings.
try:
    page_timeout = float(os.environ.get("MIRROR_PAGE_TIMEOUT", "60"))
except ValueError:
    page_timeout = 60.0

#the browser is only ever asked for element attributes - the pages themselves are downloaded with
#requests - so letting it fetch images does nothing but spend bandwidth twice and give every image on
#the page its own chance to stall the load. set MIRROR_BROWSER_IMAGES=1 to let it load them anyway,
#which is only useful when working out why a particular site misbehaves.
browser_images = os.environ.get("MIRROR_BROWSER_IMAGES", "") not in ("", "0", "no", "false")

#the pages already in the output folder when the run started, mapped to the number each sits at, so a
#next link walking the comic backwards can be told from a re-scrape walking forward over known pages
existing_pages = {}
#files dropped because a newer spelling of the same page replaced them. the archive is told, so it does
#not end up holding the page under both names.
superseded = []


#pages already saved this run, so a comic that wraps back to its first page does not restart
visited_urls = set()
#running record of what has been scraped this run, used to build the metadata file
scrape_state = {
    "first_page_url": None,
    "first_increment": None,
    "last_page_url": None,
    "last_increment": None,
    "last_image_src": None,
    "last_image_file": None,
    "pages_saved": 0,
    #where the last saved page sits according to the pages already held, so the next one can be checked
    #for having moved backwards rather than forwards
    "last_known_number": None,
    #pages this run put in the folder that were not already there. a comic that is up to date re-saves
    #the page it resumes on and finds no next link, which is a check rather than an update: it adds
    #nothing, and a run record for it would say a page was saved when none was
    "fresh_pages": 0,
    #how many pages in a row have sat earlier than the one before them. one on its own is not evidence:
    #a site that names every chapter's pages 1,2,3 hands out a name it has used before at every chapter
    #boundary, which looks backwards for exactly one page and then climbs again
    "backwards_run": 0,
    #the most comic images one address has held this run, and the first address that held more than one.
    #a comic that starts putting several pages on one address partway through would otherwise be scraped
    #as though nothing had changed, saving the first image of each page and leaving the rest behind
    #without a word
    "most_per_url": 0,
    "first_multi_url": None,
    "multi_urls": 0,
    #the page this run followed a next link to and meant to save. where a later run carries on from, and
    #deliberately not "wherever the browser ended up": a comic whose last page leads back to the front
    #page, as plenty do, leaves the browser somewhere that is not a page of the comic at all, and writing
    #that down would send the next run to the front page instead
    "walked_to": None,
    #set when a page turns out to hold no comic image at all, after this run has already saved some
    "ran_out": None,
}

def setup():
    global current_url
    global browser_images
    global verbose
    global arg_parser
    global run_start
    global run_id
    #argparse arguements
    params = argparse.ArgumentParser(description='Mirror\'s most webcomics using the selenium web driver. See the selenium documentation for more details (https://www.selenium.dev/documentation/en/).')
    params.add_argument("URL",help="This is the url that the program will start mirroring from.")
    params.add_argument("-i","--increment",type=int,help="This is the incrementation arguement. The program will save pages as this number, counting up. Defaults to 1.",default=1)
    params.add_argument("-ej","--enable_javascript",action='store_true',help="Enables javascript in the driver. Leaving it off usually makes pages load faster. Off by default.",default=False)
    params.add_argument("-f","--firefox",action='store_true',help="Uses Firefox as the webdriver browser. Exclusive with --chrome. Off by default.",default=False)
    params.add_argument("-c","--chrome",action='store_true',help="Uses Chrome as the webdriver browser. Exclusive with --firefox. This is the default.",default=False)
    params.add_argument("--headless",action=argparse.BooleanOptionalAction,help="Runs the browser without a window, which is the only way it will start on a machine with no display. On by default; pass --no-headless to watch it work.",default=True)
    params.add_argument("-m","--element_find_manual",action='store_true',help="Sets the element path for the image to be inputed manually inside the code. Off by default.",default=False)
    params.add_argument("-n","--element_find_next_manual",action='store_true',help="Sets the element path for the next button to be inputed manually inside the code. Off by default.",default=False)
    params.add_argument("-o","--output",type=str,help="Sets the output folder for the images to be saved in. Defaults to the current working directory/url.origin.")
    params.add_argument("-p","--prefix",action='store_true',help="Include the increment as a filename prefix. Useful if the comic changes filename format mid-way through.")
    params.add_argument("-v","--verbose",action='store_true',help="Output verbose logging for debugging.")
    params.add_argument("-w","--waittime",type=int,help="Time to wait before clicking next",default=0)
    params.add_argument("--cbz",action=argparse.BooleanOptionalAction,help="Packs the pages into a .cbz beside the output folder once the run finishes, adding only the pages the archive does not already hold. On by default.",default=True)
    params.add_argument("--direction-check",action=argparse.BooleanOptionalAction,default=True,help="Stop if the page after the first turns out to be one the comic already has, which means the next link is running backwards. On by default; turn it off only for a comic that genuinely reuses its filenames.")
    params.add_argument("--cbz-path",type=str,default=None,help="Where this comic's .cbz lives. Left off, an archive already beside the output folder is used, otherwise a library laid out as Uncompressed/<comic> files it as CBZs/<comic>.cbz, and failing both it goes beside the folder.")
    params.add_argument("--multi-page",action=argparse.BooleanOptionalAction,default=True,help="Save every page the comic puts on one address, not just the first. A comic that serves several pages at once is otherwise scraped a fraction at a time without saying so. On by default; --no-multi-page reads one page an address however many are there.")
    params.add_argument("--page-source",action='store_true',default=False,help="Load the page in the browser and print its html, for a page that builds itself with javascript. Saves nothing.")
    params.add_argument("--keep-index",action='store_true',default=False,help="Record each page saved - its address, its file and its size - in an index beside the settings, so the comic can be split into chapters later without being walked again. A comic that already has one keeps it up to date whether this is given or not.")
    params.add_argument("--index",type=str,default=None,metavar="FILE",help="Walk the comic without downloading anything and write one line per page - its address, its image and its title - to this file. Used to work out which saved file came from which page. An existing file is carried on from where it stopped.")
    params.add_argument("--index-first",action='store_true',default=False,help="With --index, follow the comic's first-page link before walking, for a comic whose beginning was never recorded.")
    params.add_argument("--index-limit",type=int,default=0,metavar="PAGES",help="With --index, stop after this many pages. 0 means the whole comic.")
    params.add_argument("--check",action='store_true',default=False,help="Load the page, report which of the known image and next element paths match it, and stop. Suggests paths for a site that matches none, which is the first step in adding a comic the script does not know yet.")
    params.add_argument("--prime",action='store_true',default=False,help="Save only the first page, check the next link works, write the metadata and archive, then stop. The comic is then ready for update_comics to download the rest, which is far quicker run on the machine holding the library than over a network share.")
    
    args = params.parse_args(len(sys.argv) == 1 and custom_args or None)
    arg_parser = params
    run_start = now_stamp()
    run_id = uuid.uuid4().hex

    if args.check:
        #one page, looked at once: worth loading it the way a browser really would, since a site that
        #builds its page with javascript shows nothing useful otherwise
        browser_images = True
        args.enable_javascript = True

    driver = build_driver(args)

    #the first page is fetched before the main loop begins, which puts it outside the error handling
    #that wraps the loop. left unguarded, a site that will not load ends the run with an unhandled
    #traceback and python's own exit 1 - the same code as being interrupted, so a batch run reports a
    #stalled site as though someone had stopped it by hand.
    try:
        driver.get(args.URL)
    except se.TimeoutException:
        print("\nERROR: {0} did not finish loading within {1:.0f}s. Raise MIRROR_PAGE_TIMEOUT if this "
              "site is simply slow.".format(args.URL, page_timeout))
        quit_quietly(driver)
        sys.exit(EXIT_TIMEOUT)
    except se.WebDriverException as error:
        print("\nERROR: Could not open {0}: {1}".format(args.URL, error))
        quit_quietly(driver)
        sys.exit(EXIT_DRIVER)

    #configurable vars
    increment = args.increment
    #driver.maximize_window()
    current_url = driver.current_url
    #the page this run was pointed at counts as one it means to save, so a run that falls over before it
    #saves anything still writes down where it was trying to start rather than nothing at all
    scrape_state["walked_to"] = driver.current_url
    #image format being saved. png, jpg, etc. Program will always save gif's as gifs, so no need to specify.
    format = "png"
    verbose = args.verbose
    #the parts that find elements and fetch images say what they tried only when asked
    elements.verbose = download.verbose = verbose

    #what the comic already holds, read before anything is saved, so a backwards next link is caught
    #against the pages of earlier runs rather than only the ones this run has written
    global existing_pages
    existing_pages = held_pages(output_folder(args))

    #a comic that has been walked has a record of which page is which, and chapters are built on it. it is
    #kept up to date here as pages are saved, so it never has to be walked a second time.
    open_index(output_folder(args), args)

    return driver, increment, format, args


def index_read(path):
    #what an earlier attempt already got through, so a walk that stopped can be carried on
    done = []
    if not os.path.exists(path):
        return done
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    done.append(json.loads(line))
    except (ValueError, OSError) as error:
        raise MirrorError("could not read the index at {0}: {1}".format(path, error),
                          EXIT_USAGE, "unreadable index")
    return done


def go_to_first(driver):
    for element in first_ele_names:
        if not test_next_ele_get(driver, element):
            continue
        was = driver.current_url
        if next_ele_get(driver, element) and driver.current_url != was:
            print("Followed {0} back to {1}".format(element, driver.current_url))
            return True
    print("No first-page link found, so the walk starts where it was pointed.")
    return False


def build_index(driver, args):
    #walks the comic the way a scrape does, but saves nothing: this is only about which page is which.
    #each line is written as it is reached, so a walk that is stopped or times out keeps what it had.
    path = args.index
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    done = index_read(path)
    held = {line["url"] for line in done}
    if done and args.URL and args.URL not in held:
        #pointed at a page the index does not hold. a site with one broken address in the middle - a page
        #whose title put a % into its url, say - stops a walk dead there, and the only way
        #past is to say where to pick it up. carrying on from the index's own last page instead would
        #walk into the same wall every time.
        print("Carrying on at {0}, which the index does not hold; the pages between it and page {1} are "
              "left out.".format(args.URL, len(done)))
        driver.get(args.URL)
    elif done:
        print("Carrying on from page {0} of the index ({1}).".format(len(done), done[-1]["url"]))
        driver.get(done[-1]["url"])
        if not next(driver, args):
            print("The page it stopped on has no next link, so the index is already complete.")
            return len(done)
    elif args.index_first:
        go_to_first(driver)

    at = len(done)
    seen = {line["url"] for line in done}
    #the most pages one address has held, taken from what the index already has so a walk carried on does
    #not announce the change a second time
    counts = {}
    for line in done:
        counts[line.get("url")] = counts.get(line.get("url"), 0) + 1
    most_here = max(counts.values()) if counts else 0
    started = datetime.now()
    with open(path, 'a', encoding='utf-8') as out:
        while True:
            here = driver.current_url
            if here in seen:
                print("Reached a page already in the index, so the comic has looped.")
                break
            #a line per page of the comic, not per address: where a comic serves several at once, the
            #numbering a scrape would give them is exactly the numbering recorded here
            srcs = page_images(driver, args)
            if len(srcs) > 1 and most_here < 2:
                print("{0} holds {1} pages of the comic, so each gets its own line in the "
                      "index.".format(here, len(srcs)))
            most_here = max(most_here, len(srcs))
            for src in (srcs or [None]):
                at += 1
                #the name a scrape gives this image, so the line can be matched against a saved file
                line = {"n": at, "url": here, "src": src, "file": saved_name(src) if src else None,
                        "title": driver.title}
                out.write(json.dumps(line) + chr(10))
            out.flush()
            seen.add(here)
            if not srcs:
                print("No comic image on page {0} ({1}); it is in the index as a page with no image.".format(at, here))
            if at % 25 == 0:
                gone = (datetime.now() - started).total_seconds()
                print("indexed {0} pages ({1:.0f}s, {2:.1f} a second), at {3}".format(
                    at, gone, (at - len(done)) / gone if gone else 0, here))
            if args.index_limit and at - len(done) >= args.index_limit:
                print("Stopping at {0} pages, as asked.".format(args.index_limit))
                break
            if not next(driver, args):
                print("No next link, so this is the latest page.")
                break
            if driver.current_url == here:
                print("The next link stays on the same page, so this is the latest page.")
                break
    print("Index holds {0} pages, written to {1}".format(at, path))
    return at


#set when the comic is kept in chapters, which is what decides the shape of its archives: chapters.py
#writes one per chapter from the folder, so this run must not build a single archive of the lot
in_chapters = False
#the index this comic keeps, when it has one: where it is, what it already holds, and where it is up to
index_file = None
index_urls = set()
#which pages the index already holds, as address and image together: an address serving several pages has
#a line for each, so the address on its own no longer says whether a page is in there
index_pages = set()
index_last = 0


def open_index(folder, args=None):
    global index_file, index_urls, index_pages, index_last, in_chapters
    named = None
    try:
        held = load(os.path.join(folder, metadata_file))
        named = (held.get("history") or {}).get("index_cache")
        chapters = held.get("chapters") or {}
        in_chapters = bool(chapters.get("list") or chapters.get("source_url"))
    except (OSError, ValueError, AttributeError):
        pass
    if not named and not (args and args.keep_index):
        return
    #the name chapters.py would pick for this comic's index, from the one rule both follow
    path = os.path.join(paths.index_folder(), named or paths.index_name(folder))
    if not os.path.exists(path):
        if not (args and args.keep_index):
            return
        #a comic being scraped from its first page can have its index built as it goes, which is the whole
        #of what a walk would have had to do afterwards. one being scraped from anywhere else cannot: a
        #record begun in the middle calls whatever page it starts on page one, and a walk that later
        #carries on from it stops there, having already "reached" the comic's newest page.
        if (args.increment or 1) > 1:
            print("Not starting a record of which page is which at page {0}: it has to begin at the "
                  "comic's first page, so chapters.py walks for it instead.".format(args.increment))
            return
        #every comic keeps its index in the one folder, so two starting at once can both find it missing
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'a', encoding='utf-8').close()
        print("Keeping an index of which page is which in {0}".format(path))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                held = json.loads(line)
                index_urls.add(held.get("url"))
                index_pages.add((held.get("url"), held.get("src")))
                index_last = max(index_last, held.get("n") or 0)
    except (OSError, ValueError):
        return
    index_file = path
    if index_last:
        print("This comic keeps an index of which page is which ({0} pages); new pages are added to "
              "it.".format(index_last))


def add_to_index(url, src, image, size, title):
    #one line per page, the same shape chapters.py writes, so nothing has to be walked again. a page is an
    #image, not an address: a comic serving several at once gets a line each, or the index would name one
    #of them as the whole address and chapters built on it would put the rest in the wrong place
    global index_last
    if not index_file or (url, src) in index_pages:
        return
    index_last += 1
    index_urls.add(url)
    index_pages.add((url, src))
    try:
        with open(index_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"n": index_last, "url": url, "src": src, "file": image,
                                "title": title, "bytes": size}) + chr(10))
    except OSError as error:
        print("WARNING: could not add this page to the index: {0}".format(error))


def build_driver(args):
    #the browser this run drives, with this run's settings for loading images and how long a page may take
    return browser.build_driver(args, browser_images, page_timeout)


def check_page(driver):
    #--check, against the element paths this run would try, in the order it would try them
    return pagecheck.check_page(driver, element_names, next_ele_names)


def reads_backwards(sits_at, came_from):
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


def drop_superseded(folder, increment, keeping):
    #one page should own one filename. a resume re-saves the page it starts on, and if the name that
    #lands differs from the name already there - an extension appended twice, or a hand renumbering that
    #kept only the number - the folder would hold that page twice and every reader would show it twice.
    #the freshly named file wins, so the comparison never has to happen again for this comic.
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


def output_folder(args):
    #where the pages are written; mirrors the -o argument, falling back to the url origin
    return args.output if args.output else current_url.split('/')[2]


def resume_point():
    #where a follow-up run should pick up: the page after the last saved one, if we already moved on.
    #
    #what counts as "moved on" is a page this run walked to meaning to save it - not wherever the browser
    #happens to be standing. a comic whose last page's next button goes back to the front page leaves the
    #browser on the front page, and a comic that wraps round leaves it on page one; writing either of
    #those down as the place to carry on from is how a finished comic starts itself again from the top.
    url = scrape_state["last_page_url"]
    increment = scrape_state["last_increment"]
    walked = scrape_state["walked_to"]
    if walked and walked != url:
        #a page walked to but never saved: carry on there, counting it as the page after the last saved one
        return walked, increment + 1 if increment is not None else increment
    return url, increment


def settings_from_args(args, url, increment, ended=False):
    #everything about this comic that a later run has to be told, and nothing that can be worked out
    #from it. this block is the only place any of it is written down: the command is rebuilt from here
    #when a run starts, so editing one value here is the whole of changing how a comic is scraped.
    #every key is always written, even at its default, so there is somewhere obvious to change it.
    return {
        "url": url,
        "output": output_folder(args),
        "cbz_path": args.cbz_path,
        "increment": increment,
        "prefix": bool(args.prefix),
        "javascript": bool(args.enable_javascript),
        "firefox": bool(args.firefox),
        "waittime": args.waittime,
        "cbz": bool(args.cbz),
        "direction_check": bool(args.direction_check),
        "multi_page": bool(getattr(args, "multi_page", True)),
        #not a scraping option: update_comics.py reads it and leaves a finished comic alone
        "ended": bool(ended),
    }


def metadata_save(driver, args, completed=False, exit_code=None):
    #writes the sidecar describing this scrape into the output folder, so it ends up inside the cbz
    if scrape_state["pages_saved"] == 0:
        return None
    path = os.path.join(output_folder(args), metadata_file)

    #carry over what an earlier run recorded, so a resumed comic still knows where it originally started.
    #each lookup falls back to the flat key a schema 1 file used, so an old sidecar is read and then
    #quietly rewritten in the current shape rather than needing a separate conversion first
    created = run_start
    first_page_url = scrape_state["first_page_url"]
    first_increment = scrape_state["first_increment"]
    previous, was_ended = {}, False
    old_settings, old_state, old_history = {}, {}, {}
    runs = []
    if os.path.exists(path):
        try:
            previous = load(path)
            old_settings = previous.get("settings") or {}
            old_state = previous.get("state") or {}
            old_history = previous.get("history") or {}
            created = previous.get("created", created)
            first_page_url = old_history.get("first_page_url", previous.get("first_page_url")) or first_page_url
            saved_first = old_history.get("first_page_number", previous.get("first_page_number"))
            if saved_first is not None:
                first_increment = saved_first
            #a comic marked finished by hand stays finished, even if someone runs it once more directly
            was_ended = bool(old_settings.get("ended", previous.get("ended", False)))
            #drop this run's own entry so repeated writes update it instead of stacking up
            runs = [run for run in old_history.get("runs", previous.get("runs", []))
                    if run.get("run_id") != run_id]
        except (ValueError, OSError, TypeError, AttributeError):
            pass

    #a run that put no new page in the folder is a look, not an update: a comic that is up to date
    #re-saves the page it resumes on over itself and finds no next link. writing this down would add a
    #run saying a page was saved when the comic gained none - and summing those saves counts a comic's
    #pages many times over, which is what made one comic look as though it had lost pages. it would also
    #rewrite the sidecar, and with it the archive's copy, every single day for no reason.
    #
    #unless the run before it did not end well: then this one is the news that the comic is fine again,
    #and leaving it out would leave the library showing an error that has been over for weeks.
    was_well = not runs or runs[-1].get("exit_code") in (None, EXIT_OK)
    if scrape_state["fresh_pages"] == 0 and exit_code in (None, EXIT_OK) and was_well:
        return None

    #argv is the record of what this run was actually told to do. the rendered command and the full
    #option dump that used to sit beside it said the same thing twice more, and went stale the moment
    #anyone edited the settings by hand
    runs.append({
        "run_id": run_id,
        "started": run_start,
        "updated": now_stamp(),
        "argv": sys.argv[1:],
        "start_url": args.URL,
        "start_page_number": scrape_state["first_increment"],
        "last_url": scrape_state["last_page_url"],
        "last_page_number": scrape_state["last_increment"],
        "pages_saved": scrape_state["pages_saved"],
        "completed": completed,
        "stop_reason": stop_reason,
        "exit_code": exit_code,
    })

    if len(runs) > max_runs:
        runs = runs[:1] + runs[-(max_runs - 1):]

    resume_url, resume_increment = resume_point()
    metadata = {
        "schema": 2,
        "generator": "mirror_base.py",
        "generator_version": "3.5",
        "created": created,
        "updated": now_stamp(),
        #the one place to edit. everything a run needs is built from this and nowhere else
        "settings": settings_from_args(args, resume_url, resume_increment, was_ended),
        "state": {
            "site": resume_url.split('/')[2] if resume_url and '//' in resume_url else None,
            #pages present in the folder, not saves made: a resume re-saves its starting page, so summing
            #the runs would count the overlap twice
            "page_count": len([f for f in os.listdir(output_folder(args)) if f != metadata_file]),
            "completed": completed,
            #the xpaths that actually matched this site, handy if the automatic search ever stops finding
            #them. a run that found nothing keeps whatever an earlier run discovered
            "image_xpath": image_xpath or old_state.get("image_xpath", previous.get("image_xpath")),
            "next_xpath": next_xpath or old_state.get("next_xpath", previous.get("next_xpath")),
            "last_image_url": scrape_state["last_image_src"],
            "last_image_file": scrape_state["last_image_file"],
            #the most pages one address of this comic has been seen to hold, and the first address that
            #held more than one. a run that saw nothing keeps what an earlier one found, so the change
            #stays written down for a comic that has since gone quiet
            "pages_per_url": max(scrape_state["most_per_url"],
                                 old_state.get("pages_per_url") or previous.get("pages_per_url") or 0) or None,
            "multi_page_from": scrape_state["first_multi_url"] or old_state.get("multi_page_from"),
        },
        "history": {
            #the index this comic keeps, named here so another machine, where this folder has a different
            #path, still knows which one is its own
            "index_cache": os.path.basename(index_file) if index_file else None,
            "first_page_url": first_page_url,
            "first_page_number": first_increment,
            "adopted": bool(old_history.get("adopted", previous.get("adopted", False))),
            "runs": runs,
        },
    }
    kept_from = old_history.get("adopted_from", previous.get("adopted_from"))
    if kept_from:
        metadata["history"]["adopted_from"] = kept_from
    #changes made by hand through the web page, kept so a later look can tell a setting was edited
    if old_history.get("edits"):
        metadata["history"]["edits"] = old_history["edits"]
    #what this comic is known to be missing, and which of its files were made by hand. worked out by
    #chapters.py, which takes minutes to do, so a scrape must not throw it away
    for kept in ("gaps", "gaps_note", "hand_made", "gaps_checked", "index_cache"):
        if old_history.get(kept) is not None:
            metadata["history"][kept] = old_history[kept]
    if metadata["history"].get("index_cache") is None:
        #a comic with no index says nothing rather than saying nothing twice
        del metadata["history"]["index_cache"]

    #where the chapters are, worked out by chapters.py from an archive page or the addresses
    #themselves. it describes the comic rather than this run, so a scrape must leave it alone.
    if previous.get("chapters"):
        metadata["chapters"] = previous["chapters"]

    #written aside and moved into place: this is rewritten after every page, and a run killed halfway
    #through writing it would otherwise leave a comic with no readable settings at all
    write_json(path, metadata)
    return path


def cbz_update(args):
    #packs the pages into the comic's .cbz: a new archive if there is none, and otherwise only the pages it
    #does not hold yet, added to the end
    folder = output_folder(args)
    archive = os.path.abspath(args.cbz_path) if args.cbz_path else cbz.default_path(folder)
    on_disk = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    pages = [f for f in on_disk if f != metadata_file]
    if not pages:
        return None, 0
    #a page no reader can show - a recording, a note saying where the video is - goes in as a drawn page
    #saying so, named for the file with a png on the end so it falls where the page belongs. the file
    #itself stays in the folder, which is the copy that keeps everything.
    drawn = [name for name in pages if held_otherwise(folder, name)]
    if drawn:
        print("{0} page(s) no reader can show, which the archive gets a stand-in for: {1}{2}".format(
            len(drawn), drawn[:3], "..." if len(drawn) > 3 else ""))
    if not os.path.exists(archive):
        #the metadata goes in last, as it does when one is added to, so its bytes can be reclaimed later
        cbz.write(archive, folder, pages + [name for name in on_disk if name == metadata_file])
        return archive, len(pages)
    return archive, cbz.append(archive, folder, pages, superseded)


def page_images(driver, args):
    #every comic image on the page the browser is on, in reading order, with the path that found them
    #remembered for the pages that follow
    global image_xpath
    global last_page_url, last_page_srcs, seen_on_pages
    if args.element_find_manual: #manual editing location
        #element = d.find_element(By.XPATH, '//*[@id="comic"]')
        element = driver.find_elements(By.TAG_NAME, 'img')
        return [element[0].get_attribute('src')] if element else []

    #try the path that worked last time, then fall back to searching the whole list. pages within one
    #comic can differ: most themes wrap the image in a link to the next page, so the newest page - the
    #one an update is there to fetch - has different markup to every page before it.
    srcs = []
    for element in ([image_xpath] if image_xpath else []) + element_names: #sends a possible path to be tested
        srcs = ele_get_all(driver,element)
        if srcs: #the path works, so it is remembered for the pages that follow
            image_xpath = element
            break
    if len(srcs) > 1 and not getattr(args, "multi_page", True):
        #told to read this comic as one page an address whatever the page holds
        return srcs[:1]

    #an image that was on the page before as well is the site's furniture - a button, a banner, a logo -
    #rather than a page of the comic. numbering sorts most of them out on its own, but a page whose
    #images are all unnumbered has nothing to tell them apart by - a special or a hiatus page drawn
    #outside the numbering would otherwise count first.png and archive.png as pages.
    #this needs no list of what buttons are called, which is the point: it works on a site nobody has
    #described, and on one that renames its buttons tomorrow.
    here = getattr(driver, "current_url", None)
    if here != last_page_url:
        was_here = last_page_srcs
        last_page_url, last_page_srcs = here, set(srcs)
        for src in set(srcs):
            seen_on_pages[src] = seen_on_pages.get(src, 0) + 1
        #a comic that re-uses one of its own pictures later on - an old page's image served again as a
        #much later page - shows it twice in a whole run, so twice is not enough to call something furniture.
        #a button is on every page there is, and three is plenty to tell them apart by.
        fresh = [src for src in srcs if src not in was_here and seen_on_pages.get(src, 0) < 3]
        #every one of them repeating is the same page over again, or a page whose picture really is
        #shown throughout the comic, and either way leaving it out would lose the page
        if fresh:
            srcs = fresh
    return comic_images(srcs, here)


def img_save(driver, increment, file_format, args):
    #one address, and every page of the comic on it. a site that serves several at once numbers them on
    #from where the last address left off, so the loop asks the state where it got to rather than counting.
    global current_url
    current_url = driver.current_url
    srcs = page_images(driver, args)

    if not srcs:
        #a page with no comic image on it, reached after this run has already saved some, is how a comic
        #ends on plenty of sites: the last page's next button goes back to the front page rather than
        #going nowhere. that is the comic running out, not the site being broken - and the page it landed
        #on is emphatically not somewhere to carry on from, so the last page really saved stands instead.
        if scrape_state["pages_saved"]:
            scrape_state["ran_out"] = current_url
            scrape_state["walked_to"] = scrape_state["last_page_url"]
            return False
        #the path can be perfectly right and still match nothing, because the browser runs a scrape with
        #javascript off while --check turns it on: a page that builds itself arrives empty here and full
        #there. said here, because "the path is not stored" otherwise sends you back to a path that is fine
        hint = ""
        if not getattr(args, "enable_javascript", False):
            hint = (" Javascript is off for this comic, so a page that builds itself with javascript arrives"
                    " empty - if --check finds the image and a run does not, that is why. Turn it on with"
                    " -ej, or \"javascript\": true in the comic's settings.")
        raise MirrorError("Element path for this site is not stored." + hint,
                          EXIT_NO_IMAGE, "image element not found")

    if len(srcs) > 1:
        #said once, when it changes: a comic that starts serving several pages an address goes on scraping
        #without complaint, and nothing but the page count would ever have shown the rest being left behind
        if scrape_state["most_per_url"] < 2:
            if scrape_state["pages_saved"]:
                print("{0} holds {1} pages of the comic where every address so far held one, so this comic "
                      "has started putting several pages on one address. Each is saved in turn, numbered "
                      "on from the last.".format(current_url, len(srcs)))
            else:
                print("{0} holds {1} pages of the comic, so this comic puts several pages on one address. "
                      "Each is saved in turn.".format(current_url, len(srcs)))
        if scrape_state["first_multi_url"] is None:
            scrape_state["first_multi_url"] = current_url
        scrape_state["multi_urls"] += 1
    scrape_state["most_per_url"] = max(scrape_state["most_per_url"], len(srcs))

    #a resume starts by re-saving the address it stopped on, which for several pages an address means all
    #of them. every one of them is that re-save, not a page the comic has gained
    resuming = scrape_state["pages_saved"] == 0
    for at, src in enumerate(srcs):
        save_one(driver, src, increment + at, file_format, args, resuming)
    return True


def save_one(driver, src, increment, file_format, args, resuming):
    #named the way every page is, so the index, a page put in by hand and this all agree on it
    image = saved_name(src, file_format)

    #if increment prefix is required
    if args.prefix:
        #pad with 4 zeros for sorting purposes
        image = '{0}_{1}'.format(str(increment).zfill(4), image)

    folder = output_folder(args)
    #creates the folder structure for the url origin if it does not exist
    os.makedirs(folder, exist_ok=True)

    #a backwards next link looks exactly like a working one page by page: every url is new, so the loop
    #check never fires, and the comic re-saves itself under fresh numbers until it runs out of archive.
    #recognising the page is not enough on its own, because re-scraping from an earlier point walks
    #forward over pages that are all already held. what separates the two is which way the numbers go.
    sits_at = existing_pages.get(page_key(image))
    came_from = scrape_state["last_known_number"]
    #counted whether or not the check is on, so turning it on mid-comic starts from the truth
    turned_round = reads_backwards(sits_at, came_from)
    if args.direction_check and turned_round:
        raise MirrorError(
            "{0} is page {1} of this comic and the page before it was {2}, and the page before that went "
            "backwards too, so the next link is going backwards rather than forwards. Fix the next "
            "element for this site before running it again.".format(image, sits_at, came_from),
            EXIT_BACKWARDS, "next link runs backwards")

    #the page a resume starts on gets saved a second time, under whatever name the site uses now
    if args.prefix and resuming:
        drop_superseded(folder, increment, image)

    #prefix image with output folder name or url origin for folder structure
    target = '{0}/{1}'.format(folder, image)

    #to request the url
    req = fetch(src)

    #the whole of the address a resume starts on is exempt, not just its first page: every page on it is
    #being written over itself, which is what a re-save is
    if would_lose_a_page(target, args.prefix, 0 if resuming else scrape_state["pages_saved"], req.content):
        raise MirrorError(
            "{0} is already saved here and holds a different image, so this site uses one filename for a "
            "page of every chapter. Saving it would write over the page already held. Run this comic with "
            "--prefix so each page is numbered as it is saved.".format(image),
            EXIT_SAME_NAMES, "the site reuses image names; needs --prefix")
    print('saving {0} from {1} at {2}'.format(target, src, current_url))

    #whether this page is one the folder did not have. a resume re-saves its starting page over itself,
    #which is not the comic gaining anything
    if not os.path.exists(target):
        scrape_state["fresh_pages"] += 1

    #requests and downloads the content in the url
    with open(target,'wb') as f:
        f.write(req.content)

    #track progress and rewrite the metadata each page, so it stays accurate even if the run is cut short
    if scrape_state["first_page_url"] is None:
        scrape_state["first_page_url"] = current_url
        scrape_state["first_increment"] = increment
    scrape_state["last_page_url"] = current_url
    scrape_state["last_increment"] = increment
    scrape_state["last_image_src"] = src
    scrape_state["last_image_file"] = image
    #remembered so the next page can be compared against where this one sits, and so a page saved this
    #run is recognised as held if the comic doubles back onto it later
    if sits_at is None:
        sits_at = page_number(image)
    scrape_state["last_known_number"] = sits_at
    existing_pages.setdefault(page_key(image), sits_at)
    scrape_state["pages_saved"] += 1
    visited_urls.add(current_url)
    #recorded under the name it was actually saved as, and with the size it really is, so the index needs
    #no guessing and no asking the site afterwards
    add_to_index(current_url, src, image, len(req.content), getattr(driver, "title", None))
    metadata_save(driver, args)

    return True


def next(driver,args):
    global next_xpath
    if args.waittime != 0:
        sleep(args.waittime)
    if args.element_find_next_manual: #manual editing location
        next_ele = driver.find_element(By.XPATH, '//*[@]')
        next_ele.click()
        return True

    else: #automatic mode
        #as with the image, the remembered path is tried first and the list is re-searched if it is gone.
        #a path that matches but will not press is not the end of the comic either: another path may point
        #at something that will, so the search carries on rather than taking the first failure as final
        for element in ([next_xpath] if next_xpath else []) + next_ele_names: #sends a possible path to be tested
            if not test_next_ele_get(driver,element):
                continue
            if next_ele_get(driver,element):
                next_xpath = element #the path that actually worked is the one worth trying first next time
                return True
        #nothing in the list matched, or nothing that matched could be pressed, which on an ongoing comic
        #usually just means the last page
        return False


if __name__ == "__main__":
    driver, increment, format, args = setup()
    if args.page_source:
        #whatever the browser ended up with, for something else to read
        try:
            print(driver.page_source)
        finally:
            quit_quietly(driver)
        sys.exit(EXIT_OK)
    if args.index:
        #a walk that records what it saw and downloads nothing
        code = EXIT_OK
        try:
            build_index(driver, args)
        except MirrorError as error:
            print("\nERROR: {0}".format(error))
            code = error.code
        except se.TimeoutException:
            print("\nERROR: a page took longer than {0:.0f}s to load. What the index has so far is kept, "
                  "and running it again carries on from there.".format(page_timeout))
            code = EXIT_TIMEOUT
        except (KeyboardInterrupt, SystemExit):
            print("\nStopped. What the index has so far is kept.")
            code = EXIT_INTERRUPTED
        finally:
            quit_quietly(driver)
        sys.exit(code)
    if args.check:
        #a look at one page, saving nothing: which known paths match, and what to add when none do
        try:
            check_page(driver)
            sys.exit(EXIT_OK)
        finally:
            quit_quietly(driver)
    completed = False
    exit_code = EXIT_OK
    try:
        #proceeds if it can both save an image and hit the next button.
        while img_save(driver,increment,format,args):
            if not next(driver,args):
                #the image was found, so the site is fine; the comic has simply run out of next buttons
                print("Caught up: there is no next button to press, so this is the latest page.")
                stop_reason = "no next button"
                completed = True
                break
            if current_url == driver.current_url: 
                print("Caught up: pressing next goes to the same page, so this is the latest page.")
                stop_reason = "next goes to the same page"
                completed = True
                break
            if driver.current_url in visited_urls:
                #some comics wrap from the last page back to the first, which would otherwise re-scrape everything
                print("Reached a page that was already saved this run, so the comic has looped.")
                stop_reason = "looped back to an already saved page"
                completed = True
                break
            #a page followed a next link to, and meant to be saved: this is what a later run carries on
            #from if this one stops before it gets there, and the only thing that counts as having moved on
            scrape_state["walked_to"] = driver.current_url
            if args.prime:
                #the next link has been found and followed, so the metadata resumes on the second page and the
                #rest of the comic is left for update_comics, wherever that runs
                print("Primed: saved the first page, and the next link leads to {0}. update_comics will "
                      "download the rest.".format(driver.current_url))
                stop_reason = "primed"
                break
            #asked rather than counted, because an address holding several pages uses several numbers
            increment = increment + 1 if scrape_state["last_increment"] is None \
                else scrape_state["last_increment"] + 1
        if scrape_state["ran_out"]:
            #the loop ended because the page the next link led to holds no comic at all
            print("The next link led to {0}, which has no page of the comic on it, so this is as far as the "
                  "comic goes for now. The next run carries on from {1}.".format(
                      scrape_state["ran_out"], scrape_state["last_page_url"]))
            stop_reason = "the next link led off the comic"
            completed = True
    except MirrorError as error:
        print("\nERROR: {0}".format(error))
        stop_reason = error.reason
        exit_code = error.code
    except (KeyboardInterrupt, SystemExit, ConnectionRefusedError):
        stop_reason = "exited by user"
        exit_code = EXIT_INTERRUPTED
        print("\nProgram exited by user.")
    except se.TimeoutException:
        #a page that never loads. reported on its own so a slow site is not mistaken for a broken one
        stop_reason = "page load timed out"
        exit_code = EXIT_TIMEOUT
        print("\nERROR: A page took longer than {0:.0f}s to load, so the run stopped. Raise "
              "MIRROR_PAGE_TIMEOUT if this site is simply slow.".format(page_timeout))
    except Exception as error:
        #anything else would otherwise leave python to print a traceback and exit 1, which a batch run
        #cannot tell apart from being interrupted. the error is still shown, just with its own code.
        stop_reason = "unexpected error"
        exit_code = EXIT_UNEXPECTED
        print("\nERROR: Unexpected {0}: {1}".format(type(error).__name__, error))
    finally:
        print("The last page was at {0}.".format(current_url))

        #final write, now that we know whether the comic ran to the end and where it stopped
        metadata_path = metadata_save(driver, args, completed, exit_code)
        if metadata_path:
            print("Wrote metadata to {0}.".format(metadata_path))
        elif scrape_state["fresh_pages"] == 0 and scrape_state["pages_saved"] > 0:
            #said plainly, because "saved 1 page" on a comic that gained nothing reads like an update
            print("No new pages: this comic is up to date, so nothing was written down.")

        #packed last, so the archive picks up the finished metadata along with the new pages
        if in_chapters and args.cbz and scrape_state["pages_saved"] > 0:
            print("This comic is kept in chapters, so no single archive is built; chapters.py writes one "
                  "archive per chapter.")
        if args.cbz and not in_chapters and scrape_state["pages_saved"] > 0:
            try:
                archive, added = cbz_update(args)
                if added:
                    print("Added {0} page(s) to {1}.".format(added, archive))
                elif archive:
                    print("{0} already holds every page; left untouched.".format(archive))
            except (OSError, zipfile.BadZipFile) as error:
                print("\nWARNING: Could not update the cbz: {0}".format(error))

        quit_quietly(driver)
        print("Task Completed.")

    sys.exit(exit_code)
