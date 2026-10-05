#the browser a scrape drives: which one, with javascript or without, and the limits that keep one stalled
#page from holding up a whole library. machine concerns come from the environment rather than a comic's
#settings, so they never end up pinned into one.
import os
import shlex
import sys
from time import sleep

import selenium.common.exceptions as se
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

from comiclib.exits import DRIVER as EXIT_DRIVER, TIMEOUT as EXIT_TIMEOUT, USAGE as EXIT_USAGE, MirrorError

#how long to wait before each new try at a page the browser could not load - a connection that dropped or
#timed out, a name that would not resolve, a site refusing for a while. MIRROR_RETRY_WAITS sets them, in
#seconds and comma separated
RETRY_WAITS = (5, 15, 45)


def error_page(driver):
    #whether the browser is showing its own page for a load that failed, rather than anything the site sent.
    #chrome's has an image on it - the dinosaur game's - which an image path can match, and no next link,
    #so read as a page of the comic it is the comic's last page: a walk of a comic that had thousands more
    #stopped on one, twice
    try:
        if (driver.current_url or "").startswith(("chrome-error:", "about:neterror", "about:certerror")):
            return True
        return bool(driver.find_elements(By.CSS_SELECTOR, "#main-frame-error, body.neterror"))
    except se.WebDriverException:
        return False


def retry_waits():
    given = os.environ.get("MIRROR_RETRY_WAITS")
    if not given:
        return RETRY_WAITS
    return tuple(float(bit) for bit in given.split(",") if bit.strip())


def open_page(driver, url):
    #going straight to an address. a load chrome cannot make at all - refused, reset - raises here, where
    #the same failure reached by a click does not; either way the browser is left on its error page, and
    #either way it is the same page that would not load, tried again the same way. a page that hangs, and
    #a browser that has stopped answering, are still what they were
    try:
        driver.get(url)
    except se.TimeoutException:
        raise
    except se.WebDriverException:
        if not error_page(driver):
            raise
    load_or_retry(driver)


def load_or_retry(driver):
    #a page that did not load is tried again, a little longer apart each time, before anything is read from
    #it. one that never does stops the run with the code for a page that would not load - never taken for
    #the end of the comic, which would mark it caught up part way through
    waits = retry_waits()
    for at, wait in enumerate(waits, 1):
        if not error_page(driver):
            return
        here = driver.current_url
        print("{0} did not load: the browser is showing its own error page. Trying again in {1:g}s ({2} of "
              "{3}).".format(here, wait, at, len(waits)), flush=True)
        sleep(wait)
        try:
            driver.refresh()
        except se.TimeoutException:
            pass
    if error_page(driver):
        raise MirrorError("{0} would not load after {1} tries, so the run stopped there rather than take it for "
                          "the comic's last page. The site may be down, or refusing for a while; the next run "
                          "carries on from the page before it.".format(driver.current_url, len(waits) + 1),
                          EXIT_TIMEOUT, "page would not load")

#how many pages one browser drives before a fresh one takes over. a headless chrome led through thousands of
#pages in one tab grows a little with each, and a long walk slowed as it went. that slowing turned out to be
#mostly the site - the walks that stopped part way had met pages that would not load, which load_or_retry
#now deals with - but a fresh browser costs two seconds, so it is kept as insurance against the rest.
#MIRROR_RENEW_EVERY sets it, and 0 keeps one browser for the whole run
RENEW_EVERY = 500


def quit_quietly(driver):
    #a browser that stopped answering cannot be closed politely, and saying so beats hanging or
    #raising a second error on top of whatever went wrong first
    try:
        driver.quit()
    except Exception as error:
        print("WARNING: The browser did not shut down cleanly: {0}".format(type(error).__name__))


class Renewable:
    #a browser that can be swapped for a fresh one part way through a run. everything else holds this and
    #calls it as it would the browser itself, so whatever was handed it - the walk, the page helpers, the
    #quit at the very end - goes on reaching whichever browser is current
    def __init__(self, build, every=None):
        self._build = build
        self._driver = build()
        self.every = every if every is not None else int(os.environ.get("MIRROR_RENEW_EVERY", RENEW_EVERY))
        self.pages = 0

    def __getattr__(self, name):
        return getattr(self._driver, name)

    def moved_on(self):
        #a page reached by pressing next. every so many, the browser is replaced before the page is read
        self.pages += 1
        if self.every and self.pages % self.every == 0:
            self.renew()

    def renew(self):
        #the new browser opens the page the old one was on, carrying its cookies: a site that asked once
        #whether the reader is old enough, or which theme they wanted, would otherwise ask again
        here = self._driver.current_url
        try:
            cookies = self._driver.get_cookies()
        except se.WebDriverException:
            cookies = []
        quit_quietly(self._driver)
        try:
            self._driver = self._build()
        except SystemExit:
            #build_driver ends the program when no browser will start, which in the middle of a run would
            #read as being stopped by hand. said as what it is instead, so the run records why it stopped
            raise MirrorError("a fresh browser would not start after {0} pages".format(self.pages),
                              EXIT_DRIVER, "browser would not restart")
        open_page(self._driver, here)
        kept = 0
        for cookie in cookies:
            try:
                self._driver.add_cookie(cookie)
                kept += 1
            except se.WebDriverException:
                pass
        if kept:
            #cookies only count for pages loaded after they are set
            self._driver.get(here)
        print("A fresh browser after {0} pages, carrying on at {1}.".format(self.pages, here), flush=True)


def build_driver(args, browser_images=False, page_timeout=60.0):
    #browser_images lets the browser fetch images, which a scrape never needs; page_timeout is how long
    #one page may take to load, and 0 is no limit
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
