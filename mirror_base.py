#goes through a webcomic and downloads every page. this began as a script by AChillVamp, and its loop - find
#the image, save it, press next, repeat - is still theirs; see NOTICE.

import argparse
import os
import sys
import uuid
import zipfile
from time import monotonic, sleep

import selenium.common.exceptions as se
from selenium.webdriver.common.by import By

#what this shares with the other scripts: where the settings are, what makes two filenames one page, the
#metadata file and how an archive is packed
from comiclib import browser, cbz, download, elements, exits, guards, pagecheck, runrecord, walk
from comiclib.chapters.index import KeptIndex
from comiclib.chapters.links import same_page
from comiclib.metadata import METADATA_FILE, now_stamp, read as read_metadata
from comiclib.pages import clear_unfinished, held_pages, page_key, page_number, saved_name, write_page
from comiclib.standin import held_otherwise
from comiclib.paths import element_paths_file
from comiclib.guards import would_lose_a_page
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

#the paths shipped in comiclib.elements with the library's own element_paths.json laid over them, read
#once, before anything is tried
element_names, next_ele_names = elements.with_saved_paths(element_paths_file())

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
EXIT_SKIPS = exits.SKIPS

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
#the address the comic was first scraped from, for came_round
comic_start = None
#files dropped because a newer spelling of the same page replaced them. the archive is told, so it does
#not end up holding the page under both names.
superseded = []
#the index this comic keeps, when it has one, added to as pages are saved; and whether the comic is kept
#in chapters, which decides whether this run builds a single archive at all
kept_index = KeptIndex()
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
    params = argparse.ArgumentParser(description="Downloads a webcomic page by page: opens it in a browser, saves each page's image and follows the next link until there is none. The comic's image and next link are found by trying a list of element paths, which a library extends in config/element_paths.json.")
    params.add_argument("URL",help="The address of the comic page to start from.")
    params.add_argument("-i","--increment",type=int,help="The number the first page saved counts as; each page after it counts up from there. Defaults to 1.",default=1)
    params.add_argument("-ej","--enable_javascript",action='store_true',help="Enables javascript in the driver. Leaving it off usually makes pages load faster. Off by default.",default=False)
    params.add_argument("-f","--firefox",action='store_true',help="Uses Firefox as the webdriver browser. Exclusive with --chrome. Off by default.",default=False)
    params.add_argument("-c","--chrome",action='store_true',help="Uses Chrome as the webdriver browser. Exclusive with --firefox. This is the default.",default=False)
    params.add_argument("--headless",action=argparse.BooleanOptionalAction,help="Runs the browser without a window, which is the only way it will start on a machine with no display. On by default; pass --no-headless to watch it work.",default=True)
    params.add_argument("-m","--element_find_manual",action='store_true',help="Skip the element paths and take the first image on the page, for a page that holds nothing but the comic. Off by default.",default=False)
    params.add_argument("-n","--element_find_next_manual",action='store_true',help="Press next with a path written by hand into next() in this script, instead of searching the element paths. Adding the path to element_paths.json does the same without editing anything. Off by default.",default=False)
    params.add_argument("-o","--output",type=str,help="Sets the output folder for the images to be saved in. Defaults to the current working directory/url.origin.")
    params.add_argument("-p","--prefix",action='store_true',help="Include the increment as a filename prefix. Useful if the comic changes filename format mid-way through.")
    params.add_argument("-v","--verbose",action='store_true',help="Output verbose logging for debugging.")
    params.add_argument("-w","--waittime",type=int,help="Time to wait before clicking next",default=0)
    params.add_argument("--cbz",action=argparse.BooleanOptionalAction,help="Packs the pages into a .cbz beside the output folder once the run finishes, adding only the pages the archive does not already hold. On by default.",default=True)
    params.add_argument("--direction-check",action=argparse.BooleanOptionalAction,default=True,help="Stop if the page after the first turns out to be one the comic already has, which means the next link is running backwards. On by default; turn it off only for a comic that genuinely reuses its filenames.")
    params.add_argument("--cbz-path",type=str,default=None,help="Where this comic's .cbz lives. Left off, an archive already beside the output folder is used, otherwise a library laid out as Uncompressed/<comic> files it as CBZs/<comic>.cbz, and failing both it goes beside the folder.")
    params.add_argument("--multi-page",action=argparse.BooleanOptionalAction,default=True,help="Save every page the comic puts on one address, not just the first. A comic that serves several pages at once is otherwise scraped a fraction at a time without saying so. On by default; --no-multi-page reads one page an address however many are there.")
    params.add_argument("--page-source",action='store_true',default=False,help="Load the page in the browser and print its html, for a page that builds itself with javascript. Saves nothing.")
    params.add_argument("--keep-index",action=argparse.BooleanOptionalAction,default=None,help="Record each page saved - its address, its file and its size - in an index beside the settings, so the comic can be split into chapters later without being walked again. On by default when a run starts a comic from its first page into an empty folder, which is doing everything a walk would; --no-keep-index never starts one. A comic that already has one keeps it up to date either way.")
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
    verbose = args.verbose
    #the parts that find elements and fetch images say what they tried only when asked
    elements.verbose = download.verbose = verbose

    #what the comic already holds, read before anything is saved, so a backwards next link is caught
    #against the pages of earlier runs rather than only the ones this run has written
    global existing_pages
    for name in clear_unfinished(output_folder(args)):
        print("Removed {0}, half a page left by a run that was stopped while writing it.".format(name))
    existing_pages = held_pages(output_folder(args))

    #a comic that has been walked has a record of which page is which, and chapters are built on it. it is
    #kept up to date here as pages are saved, so it never has to be walked a second time. only by a run
    #that saves pages: a walk writes its own record, and --check and --page-source save nothing at all
    if not (args.index or args.check or args.page_source):
        kept_index.open(output_folder(args), args)

    #where the comic starts, as an earlier run recorded it, for telling a comic that wraps round from its
    #newest page to its first when it keeps no record of which page is which
    global comic_start, image_xpath, next_xpath
    held = read_metadata(output_folder(args))
    history = held.get("history") or {}
    comic_start = history.get("first_page_url") if history.get("first_page_number") in (0, 1, None) else None
    #the paths that found this comic's image and pressed its next link last time are tried first, ahead of
    #the list. a site can hold two next links that both match something - one through the whole comic, one
    #only through the pages of the same series - and searching the list afresh every run took whichever
    #came first in it, which on a page of the other series was the wrong one. a path that stops matching
    #still falls back to the list, as it does part way through a run
    state = held.get("state") or {}
    if not args.element_find_manual and state.get("image_xpath"):
        image_xpath = state["image_xpath"]
    if not args.element_find_next_manual and state.get("next_xpath"):
        next_xpath = state["next_xpath"]

    return driver, increment, args


def came_round(left, reached):
    #whether the next link has led from the newest page back to the comic's beginning. a run starting on its
    #first page knows its first page as one it saved; a nightly update starting on the newest has never been
    #there, and the guard against running backwards lets one step back by, for the sites that start their
    #filenames again every chapter - after which the numbers climb, and the whole comic is saved a second
    #time. the record of which page is which says where both pages sit, whatever they are called; failing
    #that, the page the comic was first scraped from is the one it wraps to
    went = kept_index.went_back(left, reached)
    if went is not None:
        return went
    return bool(comic_start) and same_page(reached) == same_page(comic_start) and same_page(left) != same_page(comic_start)


def build_driver(args):
    #the browser this run drives, with this run's settings for loading images and how long a page may take
    return browser.build_driver(args, browser_images, page_timeout)


def check_page(driver):
    #--check, against the element paths this run would try, in the order it would try them
    return pagecheck.check_page(driver, element_names, next_ele_names)


def output_folder(args):
    #where the pages are written; mirrors the -o argument, falling back to the url origin
    return args.output if args.output else current_url.split('/')[2]


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


def still_on(driver, before, settle=3.0):
    #whether pressing next left the browser on the page it was on, which is how a comic says it has no
    #newer one. the same address, or one that differs only after the '#' and shows the very images the page
    #did - read afresh with the path that found them, so asking changes nothing page_images keeps count of
    after = driver.current_url
    if after == before:
        return True
    if not elements.moved_within(before, after) or last_page_url != before or not last_page_srcs:
        return False
    #a comic routed by its fragment changes the address first and draws the page after - on the event
    #that follows, or once a script has fetched it - so an unchanged picture read at once is only the old
    #page still showing. it is believed once it has stayed the same a while; a new one ends the wait. a
    #page slower than that ends this run there, and the next carries on from it, so nothing is lost
    until = monotonic() + settle
    while True:
        if set(ele_get_all(driver, image_xpath) if image_xpath else []) != last_page_srcs:
            return False
        if monotonic() >= until:
            return True
        sleep(0.25)


def img_save(driver, increment, args):
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
        save_one(driver, src, increment + at, args, resuming)
    return True


def save_one(driver, src, increment, args, resuming):
    #fetched before it is named, since the name is what the site says it is and the site says it in the
    #answer. nothing is written until every check below has passed
    req = fetch(src)
    #named the way every page is, so the index, a page put in by hand and this all agree on it
    image = saved_name(src, getattr(req, "headers", None), req.content)

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
    turned_round = guards.reads_backwards(sits_at, came_from, scrape_state)
    if args.direction_check and turned_round:
        raise MirrorError(
            "{0} is page {1} of this comic and the page before it was {2}, and the page before that went "
            "backwards too, so the next link is going backwards rather than forwards. Fix the next "
            "element for this site before running it again.".format(image, sits_at, came_from),
            EXIT_BACKWARDS, "next link runs backwards")

    #the page a resume starts on gets saved a second time, under whatever name the site uses now, and the
    #older spelling of it goes: by its number where pages carry one, and by what page it is where they do
    #not - a name saved with an extension tacked on, say, before names were taken as the site gives them
    if resuming:
        if args.prefix:
            guards.drop_superseded(folder, increment, image, superseded)
        else:
            guards.drop_other_spellings(folder, image, superseded)

    #prefix image with output folder name or url origin for folder structure
    target = '{0}/{1}'.format(folder, image)

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

    #written aside and moved into place, like everything else here. a run killed part way through writing
    #a page - a timeout - otherwise left half a picture under the page's own name, which the next run then
    #took for a different page held under that name and stopped on, for a comic without --prefix, for good
    write_page(target, req.content)

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
    kept_index.add(current_url, src, image, len(req.content), getattr(driver, "title", None))
    metadata_save(driver, args)

    return True


def metadata_save(driver, args, completed=False, exit_code=None):
    #the run's record in the comic's metadata, from everything this run knows so far
    return runrecord.metadata_save(
        args, output_folder(args), scrape_state=scrape_state, run_id=run_id, run_start=run_start,
        stop_reason=stop_reason, image_xpath=image_xpath, next_xpath=next_xpath, index_file=kept_index.file,
        completed=completed, exit_code=exit_code)


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


def next_instead(driver, args, left):
    #the next link just pressed skipped pages the record lists. a site can carry two that disagree - one
    #through the whole comic, one only through the pages of the same series - so the page is gone back to and
    #every other known path tried, and the first that goes to the very next page the record lists is the one
    #used from now on. False, back on the page left, when none does
    global next_xpath
    wrong = next_xpath
    for element in [path for path in next_ele_names if path != wrong]:
        driver.get(left)
        if not test_next_ele_get(driver, element) or not next_ele_get(driver, element):
            continue
        reached = driver.current_url
        if reached != left and not kept_index.skipped(left, reached) and not kept_index.went_back(left, reached):
            print("The next link {0} skips pages here, so {1} is used instead: it goes to {2}, the page that "
                  "comes next.".format(wrong, element, reached))
            next_xpath = element
            return True
    driver.get(left)
    return False


def main():
    #the scrape itself, or one of the modes that look instead: --page-source, --index and --check
    global stop_reason
    driver, increment, args = setup()
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
            walk.build_index(driver, args, page_images, next, still_on)
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
        while img_save(driver, increment, args):
            if not next(driver,args):
                #the image was found, so the site is fine; the comic has simply run out of next buttons
                print("Caught up: there is no next button to press, so this is the latest page.")
                stop_reason = "no next button"
                completed = True
                break
            if still_on(driver, current_url):
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
            if came_round(current_url, driver.current_url):
                print("Caught up: the next link has come round to {0}, which is where the comic begins, so {1} "
                      "is the latest page.".format(driver.current_url, current_url))
                stop_reason = "came round to the comic's beginning"
                completed = True
                break
            gap = kept_index.skipped(current_url, driver.current_url)
            if gap and not next_instead(driver, args, current_url):
                #stopped before anything from the far page is saved, so the next run starts where this one
                #left off rather than past pages it never fetched
                raise MirrorError(
                    "The next link from {0} skips {1} page(s) this comic's record of which page is which puts "
                    "after it, and no other next path known goes to the page that should come next. Check the "
                    "site's next link on that page, and add a path for it in the element paths.".format(
                        current_url, gap),
                    EXIT_SKIPS, "next link skips pages")
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
        if kept_index.in_chapters and args.cbz and scrape_state["pages_saved"] > 0:
            print("This comic is kept in chapters, so no single archive is built; chapters.py writes one "
                  "archive per chapter.")
        if args.cbz and not kept_index.in_chapters and scrape_state["pages_saved"] > 0:
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


if __name__ == "__main__":
    main()
