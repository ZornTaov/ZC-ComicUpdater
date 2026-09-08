#a small script to go through a webcomic and download all of the pages. #Written by AChillVamp. #V 3.4

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
import requests
import argparse
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
                  '//*[@class="navi navi-next"]', #ExterminatusNow
                  '//*[@class="navi-next"]', #consessioncomic
                  '//*[@class="col-sm-12 comic-holder"]/a', #AWARE
                  '//*[@id="maintxt"]/a[img[@src="next.gif"]]', #Double-U Tea F, GotF
                  '//*[@id="strip"]', #Questionable Content
                  '//*[@id="forwardOne"]', #Sequential Art
                  '/html/body/div[2]/div[2]/div[1]/div[2]/center/a/img', #SatW
                  '//*[contains(translate(@title,"NEXT","next"), "next")]',
                  '//*[contains(translate(@src,"NEXT","next"), "next")]',
                  '//a[contains(translate(text(),"NEXT","next"), "next")]',
                  '//*[@src="next.jpg"]',
                  '//*[@alt="Next Page"]',
                  '//*[@id="Next_"]',
                  '//*[@class="nav-next "]',
                  '//*[@id="last-path-for-happy-code"]']
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
}

def setup():
    global current_url
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
    params.add_argument("--cbz-path",type=str,default=None,help="Where this comic's .cbz lives. Left off, an archive already beside the output folder is used, otherwise a library laid out as Uncompressed/<comic> files it as CBZs/<comic>.cbz, and failing both it goes beside the folder.")
    
    args = params.parse_args(len(sys.argv) == 1 and custom_args or None)
    arg_parser = params
    run_start = now_stamp()
    run_id = uuid.uuid4().hex

    driver = build_driver(args)

    #configurable vars
    driver.get(args.URL)
    increment = args.increment
    #driver.maximize_window()
    current_url = driver.current_url
    #image format being saved. png, jpg, etc. Program will always save gif's as gifs, so no need to specify.
    format = "png"
    verbose = args.verbose

    return driver, increment, format, args


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
    else:
        options = Options()
        if args.headless:
            options.add_argument("--headless=new")
            #headless chromium falls over on the small /dev/shm found in containers and hardened services
            options.add_argument("--disable-dev-shm-usage")
        if not args.enable_javascript:
            options.add_experimental_option("prefs", {'profile.managed_default_content_settings.javascript': 2})

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
            return webdriver.Firefox(options=options, service=service) if service else webdriver.Firefox(options=options)
        return webdriver.Chrome(options=options, service=service) if service else webdriver.Chrome(options=options)
    except se.WebDriverException as error:
        print("\nERROR: Could not start the webdriver: {0}".format(error))
        sys.exit(EXIT_DRIVER)


def now_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def output_folder(args):
    #where the pages are written; mirrors the -o argument, falling back to the url origin
    return args.output if args.output else current_url.split('/')[2]


def command_line(argv):
    #renders an argument list back into a command that can be pasted into a shell
    argv = [os.path.basename(__file__)] + list(argv)
    rendered = subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)
    return 'python {0}'.format(rendered)


def rebuild_argv(args, url=None, increment=None):
    #rebuilds the arguments from the parsed namespace, skipping anything left at its default
    argv = []
    for action in arg_parser._actions:
        if action.dest in ('help', 'URL') or not action.option_strings:
            continue
        value = increment if (action.dest == 'increment' and increment is not None) else getattr(args, action.dest, None)
        if value is None or value == action.default:
            continue
        #prefer the long form, so the saved command documents itself
        positive = [f for f in action.option_strings if f.startswith('--') and not f.startswith('--no-')]
        flag = positive[-1] if positive else action.option_strings[-1]
        if action.nargs == 0: #store_true, --flag/--no-flag pairs and friends carry no value
            negative = [f for f in action.option_strings if f.startswith('--no-')]
            argv.append(negative[-1] if (negative and not value) else flag)
        else:
            argv.extend([flag, str(value)])
    argv.append(url if url else args.URL)
    return argv


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


def metadata_save(driver, args, completed=False, exit_code=None):
    #writes the sidecar describing this scrape into the output folder, so it ends up inside the cbz
    if scrape_state["pages_saved"] == 0:
        return None
    path = os.path.join(output_folder(args), metadata_file)

    #carry over what an earlier run recorded, so a resumed comic still knows where it originally started
    created = run_start
    source_url = args.URL
    first_page_url = scrape_state["first_page_url"]
    first_increment = scrape_state["first_increment"]
    previous = {}
    runs = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                previous = json.load(f)
            created = previous.get("created", created)
            source_url = previous.get("source_url", source_url)
            first_page_url = previous.get("first_page_url", first_page_url)
            first_increment = previous.get("first_page_number", first_increment)
            #drop this run's own entry so repeated writes update it instead of stacking up
            runs = [run for run in previous.get("runs", []) if run.get("run_id") != run_id]
        except (ValueError, OSError, TypeError):
            pass

    runs.append({
        "run_id": run_id,
        "started": run_start,
        "updated": now_stamp(),
        "argv": sys.argv[1:],
        "command_line": command_line(sys.argv[1:]),
        "options": vars(args),
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
        "generator": "mirror_base.py",
        "generator_version": "3.4",
        "created": created,
        "updated": now_stamp(),
        "source_url": source_url,
        "site": source_url.split('/')[2] if '//' in source_url else None,
        "output_folder": output_folder(args),
        "first_page_url": first_page_url,
        "first_page_number": first_increment,
        "last_page_url": scrape_state["last_page_url"],
        "last_page_number": scrape_state["last_increment"],
        "last_image_url": scrape_state["last_image_src"],
        "last_image_file": scrape_state["last_image_file"],
        #pages present in the folder, not saves made: a resume re-saves its starting page, so summing the
        #runs would count the overlap twice
        "page_count": len([f for f in os.listdir(output_folder(args)) if f != metadata_file]),
        "completed": completed,
        #the xpaths that actually matched this site, handy if the automatic search ever stops finding them.
        #a run that found nothing keeps whatever an earlier run discovered, so the record is not lost
        "image_xpath": image_xpath or previous.get("image_xpath"),
        "next_xpath": next_xpath or previous.get("next_xpath"),
        #the command that scrapes this comic from the top, and the one that carries on from the last page
        "command_line": command_line(rebuild_argv(args, source_url, first_increment)),
        "resume_command_line": command_line(rebuild_argv(args, resume_url, resume_increment)),
        #the same arguments as a list, so a batch updater can run them without re-parsing quoted text
        "resume_argv": rebuild_argv(args, resume_url, resume_increment),
        "runs": runs,
    }

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
    if not added:
        return cbz, 0

    with zipfile.ZipFile(cbz, 'a', zipfile.ZIP_STORED) as zf:
        meta_name = prefix + metadata_file
        last_offset = max((i.header_offset for i in zf.infolist()), default=0)
        stale = zf.NameToInfo.get(meta_name)
        internals = all(hasattr(zf, attr) for attr in ('filelist', 'NameToInfo', 'start_dir'))
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

    #prefix image with output folder name or url origin for folder structure
    folder = output_folder(args)
    image = '{0}/{1}'.format(folder, image)
    
    #creates the folder structure for the url origin if it does not exist
    if not os.path.exists(folder):
        os.makedirs(folder)

    #to request the url
    req = fetch(src)
    print('saving {0} from {1} at {2}'.format(image, src, current_url))

    #requests and downloads the content in the url
    with open(image,'wb') as f:
        f.write(req.content)
        f.close()

    #track progress and rewrite the metadata each page, so it stays accurate even if the run is cut short
    if scrape_state["first_page_url"] is None:
        scrape_state["first_page_url"] = current_url
        scrape_state["first_increment"] = increment
    scrape_state["last_page_url"] = current_url
    scrape_state["last_increment"] = increment
    scrape_state["last_image_src"] = src
    scrape_state["last_image_file"] = os.path.basename(image)
    scrape_state["pages_saved"] += 1
    visited_urls.add(current_url)
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
            increment += 1
    except MirrorError as error:
        print("\nERROR: {0}".format(error))
        stop_reason = error.reason
        exit_code = error.code
    except (KeyboardInterrupt, SystemExit, ConnectionRefusedError):
        stop_reason = "exited by user"
        exit_code = EXIT_INTERRUPTED
        print("\nProgram exited by user.")
    finally:
        print("The last page was at {0}.".format(current_url))

        #final write, now that we know whether the comic ran to the end and where it stopped
        metadata_path = metadata_save(driver, args, completed, exit_code)
        if metadata_path:
            print("Wrote metadata to {0}.".format(metadata_path))

        #packed last, so the archive picks up the finished metadata along with the new pages
        if args.cbz and scrape_state["pages_saved"] > 0:
            try:
                cbz, added = cbz_update(args)
                if added:
                    print("Added {0} page(s) to {1}.".format(added, cbz))
                elif cbz:
                    print("{0} already holds every page; left untouched.".format(cbz))
            except (OSError, zipfile.BadZipFile) as error:
                print("\nWARNING: Could not update the cbz: {0}".format(error))

        driver.quit()
        print("Task Completed.")

    sys.exit(exit_code)
