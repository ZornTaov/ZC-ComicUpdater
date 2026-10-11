#finding the comic on a page, and the link to the next one, by the element paths a library knows: which
#of them match, what image they point at, and pressing a next link however the page lets it be pressed.
import json
import os
import re
from time import monotonic, sleep
from urllib.parse import urldefrag, urlparse

import selenium.common.exceptions as se
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

#set by the scrape from its --verbose, for saying each path that did not match
verbose = False

#the paths the scripts ship with: one for each of the ways comic sites most often mark up a page, and
#examples to write a library's own from, more than a list to rely on. laid out as element_paths.json is,
#so the web page shows them as they are and a library's file is the same thing with more in it. a library
#adds its own, reorders them or turns one off in that file, never here; anything it does not mention
#keeps working, so a path shipped here later still arrives.
#an image path has to end on the <img> itself, since the page is whatever its src says. a next path is
#best kept to <a>, since a <link> in the head matches the same attributes and pressing it goes nowhere.
shipped = {
    "image": [
        {"xpath": '//*[@id="comic"]//img',
         "note": 'inside an element with the id "comic", as most WordPress comic themes have it'},
        {"xpath": '//img[@id="cc-comic"]',
         "note": "sites built on ComicControl"},
        {"xpath": '//img[@id="comic-image" or @id="comicimage" or @id="comic_image"]',
         "note": "an image whose own id says it is the comic"},
        {"xpath": '//*[contains(concat(" ", normalize-space(@class), " "), " comic ")]//img',
         "note": 'inside an element with "comic" among its classes'},
        {"xpath": '//img[@alt="Comic" or @alt="comic"]',
         "note": "an image whose alt text just says comic"},
    ],
    "next": [
        {"xpath": '//a[@rel="next"]',
         "note": "the standard mark for a link to the next page, which most comic software writes"},
        {"xpath": '//a[contains(@class, "cc-next")]',
         "note": "sites built on ComicControl"},
        {"xpath": '//a[contains(@class, "comic-nav-next")]',
         "note": "Comic Easel, and themes like it"},
        {"xpath": '//a[contains(@class, "navi-next")]',
         "note": "ComicPress, and themes like it"},
        {"xpath": '//a[starts-with(translate(normalize-space(.), "NEXT", "next"), "next")]',
         "note": 'a link whose text starts with "next", in any case'},
        {"xpath": '//a[img[starts-with(translate(@alt, "NEXT", "next"), "next")]]',
         "note": 'a picture button whose alt text starts with "next"'},
    ],
    #links back to a comic's first page, for a walk of a comic whose beginning was never recorded: it is
    #pointed at the latest page it knows, and follows one of these back to page 1 before it begins
    "first": [
        {"xpath": '//*[@rel="first"]',
         "note": "the standard mark for a link to the first page"},
        {"xpath": '//*[@class="comic-nav-base comic-nav-first"]',
         "note": "the ComicPress theme"},
        {"xpath": '//*[@class="navi navi-first"]',
         "note": "ComicPress, and themes like it"},
        {"xpath": '//*[@class="comic-nav-first"]',
         "note": "Comic Easel, and themes like it"},
        {"xpath": '//*[@title="First"]',
         "note": 'an element titled "First"'},
        {"xpath": '//*[@alt="First"]',
         "note": 'a picture button whose alt text is "First"'},
        {"xpath": '//a[contains(translate(text(),"FIRST","first"), "first")]',
         "note": 'a link whose text says "first", in any case'},
        {"xpath": '//a[img[contains(translate(@src, "FIRST", "first"), "first")]]',
         "note": 'a picture button with nothing to say what it is but its picture\'s name, as on a site '
                 'built by hand: comicfirst.gif'},
    ],
}

#the lists a scrape reads, in the order it hands them back
kinds = ("image", "next", "first")


def with_saved_paths(path):
    #the shipped lists with a library's element_paths.json laid over them, as the xpaths alone, which is
    #all a search wants: the file decides the order and which are turned off, and anything it never
    #mentions still arrives, after it - a file written before there was a list of first-page links still
    #gets every one of them
    lists = [[entry["xpath"] for entry in shipped[kind]] for kind in kinds]
    if not os.path.exists(path):
        return tuple(lists)
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            saved = json.load(f)
        return tuple(merge_paths(xpaths, saved.get(kind)) for kind, xpaths in zip(kinds, lists))
    except (ValueError, OSError, AttributeError, TypeError) as error:
        #a broken file must not stop every comic in the library, so the built-in lists carry on alone
        print("WARNING: ignoring {0}: {1}".format(path, error))
        return tuple(lists)


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


def container_of(xpath):
    #where a path looks, without what it looks for there: //*[@id="comic"] from //*[@id="comic"]/img[1].
    #a page whose comic is wrapped in a link, or drawn by something other than a picture, still has the
    #same container - so that is the place to look again, before the whole list is searched. None for a
    #path with no container to speak of, //img[@id="cc-comic"], or one that is several paths in one
    depth, quote, cut = 0, None, None
    for at, char in enumerate(xpath or ""):
        if quote:
            quote = None if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif depth == 0 and char == "|":
            return None
        elif depth == 0 and char == "/":
            cut = at
    if cut is None:
        return None
    container = xpath[:cut].rstrip("/")
    #a container of nothing - //img - or of the whole page - /html/body - is no place to look again in
    if not container or "[" not in container:
        return None
    return container


def comic_images(srcs, where=None):
    #which of several images on one address are pages of the comic. a path that matches more than one is
    #usually a comic serving several pages at once, but a path written loosely enough can also catch the
    #buttons sitting beside them. a page is numbered, because numbering pages is how every site names
    #them, and back.png and rss.png are not - so where some matches carry a number, the rest are not pages.
    #with nothing to tell them apart, every match is kept: leaving a page out is the failure worth avoiding.
    if len(srcs) < 2:
        return srcs
    numbered = [src for src in srcs if re.search(r'\d', src.rsplit('/', 1)[-1].split('?')[0])]
    if numbered and len(numbered) < len(srcs):
        left = [src.rsplit('/', 1)[-1] for src in srcs if src not in numbered]
        #named, because a walk of a few thousand pages says this a few dozen times and every one of them
        #is a page worth looking at yourself: the line is no use without knowing which page it came from
        print("{0}: ignoring {1} image(s) that carry no page number, so are not pages: {2}".format(
            where or "this page", len(left), ", ".join(left[:6])))
        return numbered
    return srcs


def test_ele_get(driver,element): #this runs through all of the possible next elements and tests them, but does not click them.
    try: #tries the path to see if it is valid
        driver.find_element(By.XPATH, element)
        return True
    except se.NoSuchElementException: #if path is not valid with this error, false is returned, making the for loop try again
        if verbose: print("\nThe element {0} could not be found.".format(element))
        return False


def ele_get(driver,element):
    try: #tries the path to see if it is valid
        element2 = driver.find_element(By.XPATH, element)
        #gets the source url of the image
        src = element2.get_attribute('src')
        return src
    except se.NoSuchElementException: #if path is not valid with this error, false is returned, making the for loop try again
        if verbose: print("\nThe element {0} src could not be found.".format(element))
        return None


def ele_get_all(driver,element):
    #every image this path matches, in the order the page lists them, rather than only the first. asking
    #for one is what makes a comic with several pages on one address look like a comic with one.
    try:
        found = driver.find_elements(By.XPATH, element)
    except se.WebDriverException:
        if verbose: print("\nThe element {0} could not be searched for.".format(element))
        return []
    srcs = []
    for one in found:
        try:
            src = one.get_attribute('src')
        except (se.StaleElementReferenceException, AttributeError):
            continue
        #the same image twice on one page is one page of the comic, however the markup repeats it
        if src and src not in srcs:
            srcs.append(src)
    return srcs


def site_of(url):
    #the site an address belongs to, with the www that some links carry and others do not left off
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def leaves_the_site(driver, one):
    #whether pressing this would take the browser to another site altogether. a path written loosely
    #enough - any element whose title mentions "next" - also matches a link in the footer to a friend's
    #site whose name happens to contain the word, and on the latest page, where the real next button is
    #gone, that link is the only match left. no comic's next page is on somebody else's site.
    try:
        link = one.find_elements(By.XPATH, "./ancestor-or-self::a[@href][1]")
        href = link[0].get_attribute("href") if link else None
        here = driver.current_url
    except (se.WebDriverException, AttributeError):
        return False
    there, ours = site_of(href), site_of(here)
    #a button that runs a script, or a link to "#", goes nowhere this can tell, so it is given the benefit
    #of the doubt. a comic on comics.example.com whose pages link to example.com is still one site
    if not there or not ours or not href.lower().startswith(("http:", "https:")):
        return False
    return not (there == ours or there.endswith("." + ours) or ours.endswith("." + there))


def next_element(driver,element):
    #the element a next path points at: the first one that can be seen, rather than simply the first. a
    #page can hold a hidden copy of its own navigation - a next button at no size at all, beside the one
    #a reader presses - and the hidden one would otherwise be what is pressed,
    #on a path that looked for all the world like it had matched. a page where every match is hidden still
    #hands back the first, since a hidden element can be pressed with a script and often has to be.
    try:
        found = driver.find_elements(By.XPATH, element)
    except se.WebDriverException:
        return None
    #a match that would leave the site is not a next link at all, so it is as though the path never
    #matched it: the search moves on, and a page where nothing else matches is the latest page
    staying = [one for one in found if not leaves_the_site(driver, one)]
    if len(staying) < len(found) and verbose:
        print("\nThe next button {0} leads to another site, so it is not this comic's.".format(element))
    found = staying
    for one in found:
        try:
            if one.is_displayed():
                return one
        except se.WebDriverException:
            continue
    return found[0] if found else None


def test_next_ele_get(driver,element): #this runs through all of the possible next elements and tests them, but does not click them.
    if next_element(driver, element) is not None:
        return True
    if verbose: print("\nThe next button {0} could not be found.".format(element))
    return False


def moved_within(before, after):
    #two addresses differing only after the '#' are one document: the browser scrolled to an anchor, or a
    #script changed its route, and nothing new was loaded. a comic whose newest page links "next" to its
    #own address with a bare '#' on the end looks, compared as text, like a page after the newest - saved
    #a second time, counted as a page of its own, and every run after numbering one further out.
    #not the same page on its own, though: a comic built by javascript can route every page by the
    #fragment, /#/page/41 to /#/page/42, so what was shown decides that
    return bool(before and after) and before != after and urldefrag(before)[0] == urldefrag(after)[0]


#the ways of pressing a next button, in the order they are tried on one not pressed before. the scrolled
#click is last because it is the only one that can wait: for a button something covers it waits out the
#whole of its timeout, where a script click answers at once
PRESSES = ("a plain click", "a script click", "a click after scrolling to it")
#the way that last pressed each next button, tried first from then on. a button something else covers - a
#sticky header, a banner - refuses a plain click, then waits out the whole of the scrolled click's timeout,
#and only then takes a script click: ten seconds on every page of a comic, for an answer that never changes
pressed_by = {}


def next_ele_get(driver,element):
    #three ways to press a link, each tried on its own. they used to be nested, which meant the script
    #click - the one that works on a page whose navigation is an onclick handler rather than a link - only
    #ever ran for a click that was intercepted, and never for one that was never possible in the first
    #place. a page like that ended every run with "there is no next button", ten seconds after there was.
    found = next_element(driver, element)
    if found is None:
        if verbose: print("\nThe next button {0} could not be found.".format(element))
        return False
    try:
        shown = found.is_displayed()
    except se.WebDriverException:
        shown = False
    #a script click a page took without going anywhere, kept as the last resort it always was
    pressed_blind = False
    for way in sorted(PRESSES, key=lambda way: way != pressed_by.get(element)):
        #waiting for an element that cannot be seen to become clickable is waiting for something that
        #cannot happen: selenium calls an element clickable only once it is displayed. it costs the whole
        #of the timeout on every page of a comic whose only next button is hidden, and the script click
        #that follows would have worked at once
        if not shown and way.startswith("a click after"):
            continue
        try:
            if way.startswith("a plain"):
                found.click()
            elif way.startswith("a click after"):
                ready = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, element)))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", ready)
                sleep(0.2)
                ready.click()
            else:
                #a hidden element, or one behind something else, still runs whatever its onclick says
                before = driver.current_url
                driver.execute_script("arguments[0].click();", found)
                #but a site that answers only a reader's own click ignores one a script makes, and says
                #nothing. taken for a press, that ends the run as though this were the latest page, so the
                #page has to be seen to move before it counts; the real click after scrolling comes next
                if not page_moved(driver, found, before):
                    if verbose:
                        print("\na script click on the next button {0} went nowhere.".format(element))
                    pressed_blind = True
                    continue
            if verbose and not way.startswith("a plain") and pressed_by.get(element) != way:
                print("\nThe next button {0} took {1}.".format(element, way))
            pressed_by[element] = way
            return True
        except (se.WebDriverException, AttributeError) as error:
            if verbose:
                print("\n{0} on the next button {1} failed: {2}".format(way, element, type(error).__name__))
    if pressed_blind:
        #nothing else would press it either. a comic that redraws its page in place, address and all, moves
        #in a way this cannot see, and the run's own check of whether it is still on the same page decides
        return True
    #the next button vanishing is how many comics end, so this stops the run rather than failing it
    if verbose: print("\nThe next button {0} could not be pressed at all.".format(element))
    return False


def page_moved(driver, pressed, before, wait=2.0):
    #whether pressing took the browser somewhere: a new address, or the page holding the button replaced.
    #a link the browser follows has already loaded by the time the script returns, so this is at once
    until = monotonic() + wait
    while True:
        try:
            if driver.current_url != before:
                return True
            pressed.is_enabled()
        except se.StaleElementReferenceException:
            return True
        except se.WebDriverException:
            return False
        if monotonic() >= until:
            return False
        sleep(0.05)
