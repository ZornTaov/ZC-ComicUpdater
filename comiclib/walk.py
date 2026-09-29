#--index: walking a comic the way a scrape does, saving nothing, to record which page is which. handed the
#scrape's own way of finding a page's images and pressing next, so a walk and a scrape cannot disagree
#about what a page is.
import json
import os
from datetime import datetime

from comiclib.chapters.index import read_index
from comiclib.elements import next_ele_get, test_next_ele_get
from comiclib.exits import USAGE as EXIT_USAGE, MirrorError
from comiclib.pages import saved_name

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


def index_read(path):
    #what an earlier attempt already got through, so a walk that stopped can be carried on
    if not os.path.exists(path):
        return []
    try:
        return read_index(path)
    except (ValueError, OSError) as error:
        raise MirrorError("could not read the index at {0}: {1}".format(path, error),
                          EXIT_USAGE, "unreadable index")


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


def build_index(driver, args, page_images, next):
    #walks the comic the way a scrape does, but saves nothing: this is only about which page is which.
    #each line is written as it is reached, so a walk that is stopped or times out keeps what it had.
    #page_images(driver, args) and next(driver, args) are the scrape's own.
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
