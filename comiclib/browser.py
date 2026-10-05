#the browser a scrape drives: which one, with javascript or without, and the limits that keep one stalled
#page from holding up a whole library. machine concerns come from the environment rather than a comic's
#settings, so they never end up pinned into one.
import os
import shlex
import sys

import selenium.common.exceptions as se
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

from comiclib.exits import DRIVER as EXIT_DRIVER, USAGE as EXIT_USAGE, MirrorError

#how many pages one browser drives before a fresh one takes over. a headless chrome led through thousands
#of pages in one tab gets slower with every page - a third of a second each at the start, four seconds each
#by the two thousandth - and then stops loading them properly: an image that is not the comic, no next link,
#and a run that takes the comic for finished halfway through. a fresh browser on the same pages is as quick
#as the first one was. MIRROR_RENEW_EVERY sets it, and 0 keeps one browser for the whole run
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
        self._driver.get(here)
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
