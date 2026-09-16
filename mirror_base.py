#a small script to go through a webcomic and download all of the pages. #Written by AChillVamp. #V 3.9

import sys

from selenium import webdriver
from selenium.webdriver import Keys, ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import selenium.common.exceptions as se
import os
import re
import requests
import argparse
import hashlib
import json
import shlex
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from time import sleep

#global vars
custom_args = [
    ]

element_names = [
                 '//*[@id="comic"]/img[1]', #concessioncomic
                 '//*[@id="page"]/img[1]',
                 '//*[@id="comic"]/a/img',
                 '//*[@id="comic"]/div/img', #ExterminatusNow
                 '//img[@alt="Comic goes here."]', #Furthia High
                 '/html/body/div/div[3]/main/section/article/div[5]/div/div/div/div/div/div/figure/div/div/img', #Scrap & Topheavy
                 '//*[@id="content"]/article/img|//*[@id="content"]/article/a/img', #TwoKinds
                 '//*[@class="comic"]',
                 '//*[@class="comic-wrap"]/img',
                 '//*[@alt="Comic"]',
                 '//*[@alt="comic"]',
                 '//*[@id="cc-comic"]',
                 '//*[@class="comic"]/img',
                 '//*[@class="ksc"]',
                 '//*[@id="main-comic"]',
                 '//*[@id="comicimage"]',
                 '/html/body/div/div[3]/img', #Sequential Art
                 '//*[@id="comic-image"]', #Housepets
                 '//*[@class="col-sm-12 comic-holder"]/a/img', #AWARE
                 '//*[@id="comicimg"]', #How MG Works
                 '//*[@id="maintxt"]/img', #Double-U Tea F, GotF, ATH
                 '//*[@id="strip"]//img', #Megatokyo
                 '//*[@id="strip"]', #Questionable Content
                 '/html/body/main/div/div/div[1]/img', #VickiFox
                 '/html/body/div[2]/div[2]/div[1]/div[2]/center/a/img', #SatW
                 '/html/body/table/tbody/tr[2]/td/table/tbody/tr/td/center/img', #DMFA
                 '/html/body/div[3]/div[1]/div[1]/img[2]', #CaptainSNES
                 '/html/body/div[1]/div[1]/div[1]/div/div[2]/img', #LICD
                 '//*[@id="last-path-for-happy-code"]']
next_ele_names = [
                  #'//*[@rel="next"]',
                  '//*[@alt="Next>"]',
                  '//*[@title="Next >"]',
                  '//*[@class="navi navi-next-in"]',
                  '//*[@class="navi comic-nav-next navi-next"]',
                  '//*[@class="comic-nav-base comic-nav-next"]',
                  '//*[@class="comic-nav-img comic-nav-img-next"]',
                  '//*[@alt="Next comic"]',
                  '//*[@id="btnNext"]',
                  '//*[@class="cc-next"]', #Snafu Comics
                  '//*[@class="navi navi-next"]', #ExterminatusNow
                  '//*[@class="navi-next"]', #consessioncomic
                  '//*[@class="col-sm-12 comic-holder"]/a', #AWARE
                  '//*[@id="maintxt"]/a[img[@src="next.gif"]]', #Double-U Tea F, GotF
                  '//*[@id="strip"]//a', #MegaTokyo
                  '//*[@id="strip"]', #Questionable Content
                  '//*[@id="forwardOne"]', #Sequential Art
                  #SatW wraps the comic image in a link to the PREVIOUS page, so matching the image
                  #here walks the comic backwards, re-saving every page it already had. the nav
                  #anchor is the real next link, and is absent on the newest page, which ends the run
                  '/html/body/div[2]/div[2]/div[1]/div[1]/a[4]', #SatW
                  '//*[contains(translate(@title,"NEXT","next"), "next")]',
                  '//*[contains(translate(@src,"NEXT","next"), "next")]',
                  '//a[contains(translate(text(),"NEXT","next"), "next")]',
                  '//*[@src="next.jpg"]',
                  '//*[@alt="Next Page"]',
                  '//*[@id="Next_"]',
                  '//*[@class="nav-next "]',
                  '//*[@id="last-path-for-happy-code"]']
#the two lists above are the ones this script ships with. a library can add to them, put them in a
#different order or turn one off without editing this file, by keeping an element_paths.json beside its
#comics - which is what the web page writes. anything the file does not mention keeps working, so a new
#entry shipped here later still arrives.
element_file = "element_paths.json"


def config_folder():
    #settings live beside the scripts rather than in the library: they describe the setup, not the comics.
    #MIRROR_CONFIG names it outright, which is how update_comics passes its own --config down to here.
    return os.environ.get("MIRROR_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config")


def element_paths_file():
    #MIRROR_ELEMENTS names the file outright; otherwise it is the one in the config folder. the two older
    #places - the folder a scrape runs from, and beside this script - are still read if nothing else is
    #there, so a library that kept its file in either goes on working.
    named = os.environ.get("MIRROR_ELEMENTS")
    if named:
        return named
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(config_folder(), element_file),
                 os.path.join(os.getcwd(), element_file),
                 os.path.join(here, element_file)):
        if os.path.exists(path):
            return path
    return os.path.join(config_folder(), element_file)


def merge_paths(shipped, saved):
    #the file decides the order, and which are turned off; anything it never mentions is added at the end
    known, ordered = set(), []
    for entry in saved or []:
        xpath = (entry or {}).get("xpath")
        if not xpath or xpath in known:
            continue
        known.add(xpath)
        if entry.get("enabled", True):
            ordered.append(xpath)
    return ordered + [xpath for xpath in shipped if xpath not in known]


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
                   '//*[@class="comic-nav-base comic-nav-first"]', #ComicPress, which kemono.cafe uses
                   '//*[@class="navi navi-first"]',
                   '//*[@class="comic-nav-first"]',
                   '//*[@title="First"]',
                   '//*[@alt="First"]',
                   '//a[contains(translate(text(),"FIRST","first"), "first")]']

#the xpaths that matched this comic, cached so each page does not repeat the whole search. kept in their
#own variables rather than written back into the lists above, so a re-search still has every candidate.
image_xpath = None
next_xpath = None
current_url = None
verbose = False

#name of the sidecar written into the output folder, so it gets zipped into the cbz alongside the pages
metadata_file = "mirror_metadata.json"
#how many run records to keep. a monthly updater would otherwise grow this file forever; the first run is
#always kept, since it is the one that says how the comic was originally scraped
max_runs = 20
arg_parser = None
run_start = None
#identifies this run in the metadata; a timestamp alone collides when a comic is scraped twice in one second
run_id = None
stop_reason = "incomplete"
#exit codes, so a batch driver can tell an ordinary update from a site that broke
EXIT_OK = 0
EXIT_INTERRUPTED = 1
EXIT_USAGE = 2
EXIT_NO_IMAGE = 3
EXIT_DOWNLOAD = 4
EXIT_DRIVER = 5
EXIT_TIMEOUT = 6
EXIT_UNEXPECTED = 7
EXIT_BACKWARDS = 8

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


class MirrorError(Exception):
    #a scrape failure that should end the run with a specific exit code
    def __init__(self, message, code, reason):
        super().__init__(message)
        self.code = code
        self.reason = reason


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
    #image format being saved. png, jpg, etc. Program will always save gif's as gifs, so no need to specify.
    format = "png"
    verbose = args.verbose

    #what the comic already holds, read before anything is saved, so a backwards next link is caught
    #against the pages of earlier runs rather than only the ones this run has written
    global existing_pages
    existing_pages = folder_pages(output_folder(args))

    #a comic that has been walked has a record of which page is which, and chapters are built on it. it is
    #kept up to date here as pages are saved, so it never has to be walked a second time.
    open_index(output_folder(args), args)

    return driver, increment, format, args


def describe_element(driver, element):
    #enough to tell two matches apart when neither is the one that was wanted
    try:
        tag = element.tag_name
        bits = {"tag": tag}
        for name in ("id", "class", "alt", "title", "rel", "src", "href"):
            value = element.get_attribute(name)
            if value:
                bits[name] = value[:200]
        if tag == "img":
            size = element.size
            bits["size"] = "{0:.0f}x{1:.0f}".format(size.get("width", 0), size.get("height", 0))
        return bits
    except se.WebDriverException:
        return {}


def suggest_paths(driver):
    #for a site nothing matched: the big images, and the links that look like a next button
    images, links = [], []
    try:
        for found in driver.find_elements(By.TAG_NAME, 'img')[:80]:
            size = found.size
            area = size.get("width", 0) * size.get("height", 0)
            if area < 40000: #smaller than 200x200 is a button or an avatar, not a comic page
                continue
            bits = describe_element(driver, found)
            bits["area"] = area
            bits["suggested"] = ('//*[@id="{0}"]'.format(bits["id"]) if bits.get("id") else
                                 '//img[@alt="{0}"]'.format(bits["alt"]) if bits.get("alt") else
                                 '//*[@class="{0}"]/img'.format(bits["class"]) if bits.get("class") else None)
            images.append(bits)
        spare = []
        for found in driver.find_elements(By.TAG_NAME, 'a')[:200]:
            label = found.text or ""
            described = label + " " + " ".join(
                str(found.get_attribute(name) or "") for name in ("title", "rel", "class", "id"))
            bits = describe_element(driver, found)
            bits["suggested"] = ('//*[@id="{0}"]'.format(bits["id"]) if bits.get("id") else
                                 '//*[@class="{0}"]'.format(bits["class"]) if bits.get("class") else None)
            if not bits.get("suggested") or not bits.get("href"):
                continue
            if "next" in described.lower() or ">" in label or "→" in label or "»" in label:
                links.append(bits)
            elif 0 < len(label.strip()) <= 20:
                #plenty of comics label the link something else entirely - onwards, forward, an arrow -
                #so short links are kept as a second best rather than leaving the list empty
                spare.append(bits)
        links = links or spare
    except se.WebDriverException as error:
        print("could not look over the page: {0}".format(error))
    images.sort(key=lambda bits: -bits.get("area", 0))
    return images[:5], links[:5]


def check_page(driver):
    #every path that matches, in the order a scrape would try them, so it is clear which one would win
    found = {"url": driver.current_url, "title": driver.title, "image": [], "next": []}
    for element in element_names:
        src = ele_get(driver, element)
        if src:
            found["image"].append({"xpath": element, "src": src})
    for element in next_ele_names:
        if test_next_ele_get(driver, element):
            try:
                bits = describe_element(driver, driver.find_element(By.XPATH, element))
            except se.WebDriverException:
                bits = {}
            found["next"].append({"xpath": element, "found": bits})
    if not found["image"] or not found["next"]:
        images, links = suggest_paths(driver)
        found["suggestions"] = {"image": images, "next": links}

    print("Checked {0}".format(found["url"]))
    for kind in ("image", "next"):
        if found[kind]:
            print("  {0}: {1} of the known paths match; a scrape would use {2}".format(
                kind, len(found[kind]), found[kind][0]["xpath"]))
        else:
            print("  {0}: nothing matched".format(kind))
            for guess in found.get("suggestions", {}).get(kind, []):
                print("    maybe {0}  ({1})".format(guess.get("suggested"), describe_guess(guess)))
    #a machine readable copy on one line, for the web page to read back
    print("CHECK-JSON {0}".format(json.dumps(found)))
    return found


def describe_guess(guess):
    return ", ".join("{0}={1}".format(key, guess[key]) for key in ("tag", "size", "alt", "class", "id", "href")
                     if guess.get(key))


def index_name(src, file_format="png"):
    #the name img_save would give this image, so a line in the index can be matched against a saved file
    name = src[src.rfind("/") + 1:]
    if "gif" in src:
        file_format = "gif"
    return name if name.lower().endswith(file_format) else "{0}.{1}".format(name, file_format)


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
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    done = index_read(path)
    if done:
        print("Carrying on from page {0} of the index ({1}).".format(len(done), done[-1]["url"]))
        driver.get(done[-1]["url"])
        if not next(driver, args):
            print("The page it stopped on has no next link, so the index is already complete.")
            return len(done)
    elif args.index_first:
        go_to_first(driver)

    at = len(done)
    seen = {line["url"] for line in done}
    started = datetime.now()
    with open(path, 'a', encoding='utf-8') as out:
        while True:
            here = driver.current_url
            if here in seen:
                print("Reached a page already in the index, so the comic has looped.")
                break
            src = None
            for element in ([image_xpath] if image_xpath else []) + element_names:
                src = ele_get(driver, element)
                if src:
                    break
            at += 1
            line = {"n": at, "url": here, "src": src, "file": index_name(src) if src else None,
                    "title": driver.title}
            out.write(json.dumps(line) + chr(10))
            out.flush()
            seen.add(here)
            if src is None:
                print("No comic image on page {0} ({1}); it is in the index as a page with no image.".format(at, here))
            if at % 25 == 0:
                gone = (datetime.now() - started).total_seconds()
                print("indexed {0} pages ({1:.0f}s, {2:.1f} a second), at {3}".format(
                    at, gone, (at - len(done)) / gone if gone else 0, here))
            if args.index_limit and at - len(done) >= args.index_limit:
                print("Stopping at {0} pages, as asked.".format(args.index_limit))
                break
            if not next(driver, args):
                print("No next link, so that is the end of the comic.")
                break
            if driver.current_url == here:
                print("The next link stays on the same page, so that is the end of the comic.")
                break
    print("Index holds {0} pages, written to {1}".format(at, path))
    return at


#set when the comic is kept in chapters, which is what decides the shape of its archives: chapters.py
#writes one per chapter from the folder, so this run must not build a single archive of the lot
in_chapters = False
#the index this comic keeps, when it has one: where it is, what it already holds, and where it is up to
index_file = None
index_urls = set()
index_last = 0


def index_name(folder):
    #the same name chapters.py would pick for this comic, so the two always mean one file
    full = os.path.abspath(folder)
    tag = hashlib.sha1(full.replace(os.sep, '/').lower().encode('utf-8')).hexdigest()[:8]
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(full)).strip('_') or "comic"
    return "{0}.{1}.jsonl".format(stem, tag)


def open_index(folder, args=None):
    global index_file, index_urls, index_last, in_chapters
    named = None
    try:
        with open(os.path.join(folder, metadata_file), 'r', encoding='utf-8') as f:
            held = json.load(f)
        named = (held.get("history") or {}).get("index_cache")
        chapters = held.get("chapters") or {}
        in_chapters = bool(chapters.get("list") or chapters.get("source_url"))
    except (OSError, ValueError, AttributeError):
        pass
    if not named and not (args and args.keep_index):
        return
    path = os.path.join(config_folder(), "index", named or index_name(folder))
    if not os.path.exists(path):
        if not (args and args.keep_index):
            return
        #a comic being scraped from its first page can have its index built as it goes, which is the whole
        #of what a walk would have had to do afterwards
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
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
                index_last = max(index_last, held.get("n") or 0)
    except (OSError, ValueError):
        return
    index_file = path
    if index_last:
        print("This comic keeps an index of which page is which ({0} pages); new pages are added to "
              "it.".format(index_last))


def add_to_index(url, src, image, size, title):
    #one line per page, the same shape chapters.py writes, so nothing has to be walked again
    global index_last
    if not index_file or url in index_urls:
        return
    index_last += 1
    index_urls.add(url)
    try:
        with open(index_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"n": index_last, "url": url, "src": src, "file": image,
                                "title": title, "bytes": size}) + chr(10))
    except OSError as error:
        print("WARNING: could not add this page to the index: {0}".format(error))


def quit_quietly(driver):
    #a browser that stopped answering cannot be closed politely, and saying so beats hanging or
    #raising a second error on top of whatever went wrong first
    try:
        driver.quit()
    except Exception as error:
        print("WARNING: The browser did not shut down cleanly: {0}".format(type(error).__name__))


def build_driver(args):
    #the browser choice and the javascript toggle are independent, so either browser can run headless
    if args.firefox and args.chrome:
        print("\nERROR: --firefox and --chrome cannot be used together.")
        sys.exit(EXIT_USAGE)

    if args.firefox:
        options = FirefoxOptions()
        if args.headless:
            options.add_argument("--headless")
        if not args.enable_javascript:
            options.set_preference("javascript.enabled", False)
        if not browser_images:
            options.set_preference("permissions.default.image", 2)
    else:
        options = Options()
        if args.headless:
            options.add_argument("--headless=new")
            #headless chromium falls over on the small /dev/shm found in containers and hardened services
            options.add_argument("--disable-dev-shm-usage")
        prefs = {}
        if not args.enable_javascript:
            prefs['profile.managed_default_content_settings.javascript'] = 2
        if not browser_images:
            prefs['profile.managed_default_content_settings.images'] = 2
        if prefs:
            options.add_experimental_option("prefs", prefs)

    #a page is finished being useful as soon as its html is parsed, since only attributes are read from
    #it. waiting for the load event means waiting for every stylesheet, font and iframe as well, any one
    #of which can hang without the page looking broken in a browser. with javascript enabled the wait is
    #kept, because then the comic may well be inserted by a script that has not run yet.
    if not args.enable_javascript:
        options.page_load_strategy = 'eager'

    #extra browser flags for the machine this runs on, such as --no-sandbox inside a container, where
    #chromium's own sandbox has no namespaces to work with
    for flag in shlex.split(os.environ.get("MIRROR_BROWSER_ARGS", "")):
        options.add_argument(flag)

    #machine specific paths come from the environment rather than arguments, so they stay out of the saved
    #commands in the metadata. needed wherever selenium cannot download a matching driver itself.
    browser_binary = os.environ.get("MIRROR_BROWSER_BINARY")
    driver_binary = os.environ.get("MIRROR_DRIVER_BINARY")
    if browser_binary:
        options.binary_location = browser_binary
    service = None
    if driver_binary:
        service = FirefoxService(executable_path=driver_binary) if args.firefox else ChromeService(executable_path=driver_binary)

    try:
        if args.firefox:
            driver = webdriver.Firefox(options=options, service=service) if service else webdriver.Firefox(options=options)
        else:
            driver = webdriver.Chrome(options=options, service=service) if service else webdriver.Chrome(options=options)
    except se.WebDriverException as error:
        print("\nERROR: Could not start the webdriver: {0}".format(error))
        sys.exit(EXIT_DRIVER)

    #without these a page that never finishes loading stalls the whole run. a comic that hangs holds up
    #every comic queued behind it, so the limit matters more to a batch than to a single scrape.
    if page_timeout > 0:
        try:
            driver.set_page_load_timeout(page_timeout)
            driver.set_script_timeout(page_timeout)
        except se.WebDriverException:
            #an older driver may not accept them; the run is still worth attempting
            pass
    return driver


def page_key(name):
    #what makes two filenames the same page, ignoring how each happened to be named: the '0742_' this
    #script adds in front moves whenever a comic is renumbered, and an extension has been appended to
    #names that already had one. so '0742_a-page.png.png' and 'a-page.png' are one page.
    #a number followed by a dot is NOT stripped - for a comic whose pages the site names '0005.gif',
    #that number is the only thing telling one page from another.
    stem = re.sub(r'^\d{3,}_', '', name)
    stem = re.sub(r'\.(png|jpe?g|gif|webp)\.(png|jpe?g|gif|webp)$', r'.\1', stem, flags=re.I)
    return stem.lower()


def page_number(name):
    #the page number a filename carries, from the prefix this script adds or from a name that is just
    #the number. none when the name says nothing about where the page sits.
    found = re.match(r'^(\d+)[_.]', name)
    return int(found.group(1)) if found else None


def folder_pages(folder):
    #what is on disk already, as page identity to page number, so a page is recognised however it was
    #named last time and its position is known
    held = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return held
    for name in names:
        if name == metadata_file or not os.path.isfile(os.path.join(folder, name)):
            continue
        held.setdefault(page_key(name), page_number(name))
    return held


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


def now_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def output_folder(args):
    #where the pages are written; mirrors the -o argument, falling back to the url origin
    return args.output if args.output else current_url.split('/')[2]


def resume_point(driver):
    #where a follow-up run should pick up: the page after the last saved one, if we already moved on
    url = scrape_state["last_page_url"]
    increment = scrape_state["last_increment"]
    try:
        if driver.current_url and driver.current_url != url:
            return driver.current_url, increment + 1
    except Exception:
        pass
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
            with open(path, 'r', encoding='utf-8') as f:
                previous = json.load(f)
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

    resume_url, resume_increment = resume_point(driver)
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

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
        f.write('\n')
    return path


def fetch(url, attempts=3):
    #retries briefly so a blip does not end an unattended run, then gives up loudly rather than
    #writing an error page to disk under an image filename
    for attempt in range(1, attempts + 1):
        try:
            req = requests.get(url, stream=True, timeout=30, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"})
            if req.status_code != 200:
                raise requests.RequestException("HTTP {0}".format(req.status_code))
            return req
        except requests.RequestException as error:
            if attempt == attempts:
                raise MirrorError("Could not download {0}: {1}".format(url, error), EXIT_DOWNLOAD, "download failed")
            if verbose: print("\nAttempt {0} for {1} failed ({2}); retrying.".format(attempt, url, error))
            sleep(2 * attempt)


def archive_prefix(zf, folder):
    #archives built by Compress-Archive put every entry under the folder name, while a plain zip of the
    #contents does not. new entries have to match whichever this archive already uses, or a reader shows
    #the comic as two separate groups
    prefix = os.path.basename(os.path.abspath(folder)) + '/'
    names = zf.namelist()
    return prefix if names and all(name.startswith(prefix) for name in names) else ''


def cbz_default(folder):
    #where the archive goes when --cbz-path is not given. a library that keeps its pages under an
    #Uncompressed folder and its archives in a matching CBZs tree gets them filed there, so the plain
    #command puts a new comic where the reader is already looking rather than among the loose pages.
    folder = os.path.abspath(folder)
    beside = folder + '.cbz'
    if os.path.exists(beside):
        #an archive already sitting next to its folder keeps its place. filing it somewhere new would
        #start a second archive and leave the reader pointed at one that quietly stops growing.
        return beside
    parts = folder.replace('\\', '/').split('/')
    #the last part is the comic itself and the first is the drive or root, so neither can be the shelf
    for at in range(len(parts) - 2, 0, -1):
        if parts[at].lower() != 'uncompressed':
            continue
        shelf = os.sep.join(parts[:at] + ['CBZs'])
        if os.path.isdir(shelf):
            return os.sep.join([shelf] + parts[at + 1:]) + '.cbz'
    return beside


def cbz_update(args):
    #packs the pages into a .cbz beside the folder. a zip keeps its entries in the order they were written
    #and rewrites only the directory at the end, so appending leaves every existing byte where it is and a
    #sync has to carry no more than the new pages.
    folder = output_folder(args)
    cbz = os.path.abspath(args.cbz_path) if args.cbz_path else cbz_default(folder)
    on_disk = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    pages = [f for f in on_disk if f != metadata_file]
    if not pages:
        return None, 0

    if not os.path.exists(cbz):
        #an explicit path may point somewhere that does not exist yet
        parent = os.path.dirname(cbz)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        #images are already compressed, so storing them saves the cpu for no meaningful size difference
        with zipfile.ZipFile(cbz, 'w', zipfile.ZIP_STORED) as zf:
            for name in pages:
                zf.write(os.path.join(folder, name), name)
            if metadata_file in on_disk:
                zf.write(os.path.join(folder, metadata_file), metadata_file)
        return cbz, len(pages)

    #read first, so an archive with nothing to add is left untouched rather than having its directory
    #rewritten, which would make a sync re-checksum the whole file for no reason
    with zipfile.ZipFile(cbz) as zf:
        prefix = archive_prefix(zf, folder)
        existing = set(zf.namelist())
    added = [name for name in pages if prefix + name not in existing]
    #a page whose filename was replaced this run has to leave the archive under its old name too, or the
    #comic shows that page twice for good
    stale_pages = [prefix + name for name in superseded if prefix + name in existing]
    if not added and not stale_pages:
        return cbz, 0

    with zipfile.ZipFile(cbz, 'a', zipfile.ZIP_STORED) as zf:
        meta_name = prefix + metadata_file
        last_offset = max((i.header_offset for i in zf.infolist()), default=0)
        internals = all(hasattr(zf, attr) for attr in ('filelist', 'NameToInfo', 'start_dir'))
        if internals:
            for name in stale_pages:
                gone = zf.NameToInfo.get(name)
                if gone is None:
                    continue
                #the bytes stay where they are and simply stop being referenced, which no reader looks
                #at; only the directory has to forget the name
                zf.filelist.remove(gone)
                del zf.NameToInfo[name]
                print("Removed the superseded {0} from the archive.".format(name))
        stale = zf.NameToInfo.get(meta_name)
        if stale is not None and internals:
            #drop the old copy from the directory so the refreshed one does not leave a duplicate entry.
            #this script always writes the metadata last, so its bytes can usually be reclaimed; in an
            #archive built elsewhere it may sit anywhere, and those few bytes are simply left unreferenced,
            #which no reader ever looks at.
            was_last = stale.header_offset == last_offset
            zf.filelist.remove(stale)
            del zf.NameToInfo[meta_name]
            if was_last:
                zf.start_dir = stale.header_offset
        for name in added:
            zf.write(os.path.join(folder, name), prefix + name)
        if metadata_file in on_disk:
            zf.write(os.path.join(folder, metadata_file), meta_name)
    return cbz, len(added)


def img_save(driver, increment, file_format, args):
    global image_xpath
    global current_url
    src = None
    current_url = driver.current_url

    if args.element_find_manual: #manual editing location
        #element = d.find_element(By.XPATH, '//*[@id="comic"]')
        element = driver.find_elements(By.TAG_NAME, 'img')
        src = element[0].get_attribute('src')

    else: #automatic mode
        #try the path that worked last time, then fall back to searching the whole list. pages within one
        #comic can differ: most themes wrap the image in a link to the next page, so the newest page - the
        #one an update is there to fetch - has different markup to every page before it.
        if image_xpath:
            src = ele_get(driver,image_xpath)
        if src is None:
            for element in element_names: #sends a possible path to be tested
                src = ele_get(driver,element)
                if src: #the path works, so it is remembered for the pages that follow
                    image_xpath = element
                    break

    if src == None:
        raise MirrorError("Element path for this site is not stored.", EXIT_NO_IMAGE, "image element not found")

    #will save the file as a .gif instead of a .png
    if "gif" in src:
        file_format = 'gif'
    pos = src.rfind("/")
    
    #sets name of image to be saved as
    #if src is not postfixed with file_format ignoring case, it will be added to the end of the filename.
    image = src[pos+1:]
    if not image.lower().endswith(file_format):
        image = '{0}.{1}'.format(image, file_format)

    #if increment prefix is required
    if args.prefix:
        #pad with 4 zeros for sorting purposes
        image = '{0}_{1}'.format(str(increment).zfill(4), image)

    folder = output_folder(args)
    #creates the folder structure for the url origin if it does not exist
    if not os.path.exists(folder):
        os.makedirs(folder)

    #a backwards next link looks exactly like a working one page by page: every url is new, so the loop
    #check never fires, and the comic re-saves itself under fresh numbers until it runs out of archive.
    #recognising the page is not enough on its own, because re-scraping from an earlier point walks
    #forward over pages that are all already held. what separates the two is which way the numbers go.
    sits_at = existing_pages.get(page_key(image))
    came_from = scrape_state["last_known_number"]
    if (args.direction_check and sits_at is not None and came_from is not None
            and sits_at < came_from):
        raise MirrorError(
            "{0} is page {1} of this comic and the page before it was {2}, so the next link is going "
            "backwards rather than forwards. Fix the next element for this site before running it "
            "again.".format(image, sits_at, came_from),
            EXIT_BACKWARDS, "next link runs backwards")

    #the page a resume starts on gets saved a second time, under whatever name the site uses now
    if args.prefix and scrape_state["pages_saved"] == 0:
        drop_superseded(folder, increment, image)

    #prefix image with output folder name or url origin for folder structure
    target = '{0}/{1}'.format(folder, image)

    #to request the url
    req = fetch(src)
    print('saving {0} from {1} at {2}'.format(target, src, current_url))

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
        #as with the image, the remembered path is tried first and the list is re-searched if it is gone
        if next_xpath and test_next_ele_get(driver,next_xpath):
            return next_ele_get(driver,next_xpath)
        for element in next_ele_names: #sends a possible path to be tested
            if test_next_ele_get(driver,element):
                next_xpath = element
                return next_ele_get(driver,element)
        #nothing in the list matched, which on an ongoing comic usually just means the last page
        return False


def test_ele_get(driver,element): #this runs through all of the possible next elements and tests them, but does not click them.
    global verbose
    try: #tries the path to see if it is valid
        driver.find_element(By.XPATH, element)
        return True
    except se.NoSuchElementException: #if path is not valid with this error, false is returned, making the for loop try again
        if verbose: print("\nThe element {0} could not be found.".format(element))
        return False

def ele_get(driver,element):
    global verbose
    try: #tries the path to see if it is valid
        element2 = driver.find_element(By.XPATH, element)
        #gets the source url of the image
        src = element2.get_attribute('src')
        return src
    except se.NoSuchElementException: #if path is not valid with this error, false is returned, making the for loop try again
        if verbose: print("\nThe element {0} src could not be found.".format(element))
        return None


def test_next_ele_get(driver,element): #this runs through all of the possible next elements and tests them, but does not click them.
    global verbose
    try: #tries the path to see if it is valid
        driver.find_element(By.XPATH, element)
        return True
    except se.NoSuchElementException: #if path is not valid with this error, false is returned, making the for loop try again
        if verbose: print("\nThe next button {0} could not be found.".format(element))
        return False


def next_ele_get(driver,element):
    global verbose
    try: #try to do a basic click
        driver.find_element(By.XPATH, element).click()
        return True
    except (se.NoSuchElementException, AttributeError, se.ElementNotInteractableException, se.ElementClickInterceptedException):
        try: #try to scroll to the element then click it
            wait = WebDriverWait(driver, 10)
            ele = wait.until(EC.element_to_be_clickable((By.XPATH, element)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", ele)
            sleep(0.2)
            try:
                ele.click()
            except se.ElementClickInterceptedException:
                #try to click the element using JavaScript
                if verbose: print("\nThe next button {0} was intercepted; trying a JavaScript click.".format(element))
                driver.execute_script("arguments[0].click();", ele)
            return True
        except (se.NoSuchElementException, AttributeError, se.ElementNotInteractableException, se.TimeoutException, se.StaleElementReferenceException):
            #the next button vanishing is how many comics end, so this stops the run rather than failing it
            if verbose: print("\nThe next button {0} could not be clicked.".format(element))
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
                print("Reached last page since there is no next button to press!")
                stop_reason = "no next button"
                completed = True
                break
            if current_url == driver.current_url: 
                print("Reached last page since pressing Next goes to the same page!")
                stop_reason = "next goes to the same page"
                completed = True
                break
            if driver.current_url in visited_urls:
                #some comics wrap from the last page back to the first, which would otherwise re-scrape everything
                print("Reached a page that was already saved this run, so the comic has looped.")
                stop_reason = "looped back to an already saved page"
                completed = True
                break
            if args.prime:
                #the next link has been found and followed, so the metadata resumes on the second page and the
                #rest of the comic is left for update_comics, wherever that runs
                print("Primed: saved the first page, and the next link leads to {0}. update_comics will "
                      "download the rest.".format(driver.current_url))
                stop_reason = "primed"
                break
            increment += 1
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

        #packed last, so the archive picks up the finished metadata along with the new pages
        if in_chapters and args.cbz and scrape_state["pages_saved"] > 0:
            print("This comic is kept in chapters, so no single archive is built; chapters.py writes one "
                  "archive per chapter.")
        if args.cbz and not in_chapters and scrape_state["pages_saved"] > 0:
            try:
                cbz, added = cbz_update(args)
                if added:
                    print("Added {0} page(s) to {1}.".format(added, cbz))
                elif cbz:
                    print("{0} already holds every page; left untouched.".format(cbz))
            except (OSError, zipfile.BadZipFile) as error:
                print("\nWARNING: Could not update the cbz: {0}".format(error))

        quit_quietly(driver)
        print("Task Completed.")

    sys.exit(exit_code)
