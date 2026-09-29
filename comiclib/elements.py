#finding the comic on a page, and the link to the next one, by the element paths a library knows: which
#of them match, what image they point at, and pressing a next link however the page lets it be pressed.
import re
from time import sleep

import selenium.common.exceptions as se
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

#set by the scrape from its --verbose, for saying each path that did not match
verbose = False


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


def ele_get_all(driver,element):
    #every image this path matches, in the order the page lists them, rather than only the first. asking
    #for one is what makes a comic with several pages on one address look like a comic with one.
    global verbose
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
    for one in found:
        try:
            if one.is_displayed():
                return one
        except se.WebDriverException:
            continue
    return found[0] if found else None


def test_next_ele_get(driver,element): #this runs through all of the possible next elements and tests them, but does not click them.
    global verbose
    if next_element(driver, element) is not None:
        return True
    if verbose: print("\nThe next button {0} could not be found.".format(element))
    return False


def next_ele_get(driver,element):
    #three ways to press a link, each tried on its own. they used to be nested, which meant the script
    #click - the one that works on a page whose navigation is an onclick handler rather than a link - only
    #ever ran for a click that was intercepted, and never for one that was never possible in the first
    #place. a page like that ended every run with "there is no next button", ten seconds after there was.
    global verbose
    found = next_element(driver, element)
    if found is None:
        if verbose: print("\nThe next button {0} could not be found.".format(element))
        return False
    try:
        shown = found.is_displayed()
    except se.WebDriverException:
        shown = False
    for way in ("a plain click", "a click after scrolling to it", "a script click"):
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
                driver.execute_script("arguments[0].click();", found)
            if verbose and not way.startswith("a plain"):
                print("\nThe next button {0} took {1}.".format(element, way))
            return True
        except (se.WebDriverException, AttributeError) as error:
            if verbose:
                print("\n{0} on the next button {1} failed: {2}".format(way, element, type(error).__name__))
    #the next button vanishing is how many comics end, so this stops the run rather than failing it
    if verbose: print("\nThe next button {0} could not be pressed at all.".format(element))
    return False
