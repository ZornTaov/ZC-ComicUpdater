#--check: a look at one page, saving nothing - which of the known element paths match it, and what to add
#when none do. the first step in adding a comic the element paths do not know yet.
import json

import selenium.common.exceptions as se
from selenium.webdriver.common.by import By

from comiclib.download import fetch
from comiclib.elements import comic_images, ele_get_all, test_next_ele_get
from comiclib.exits import MirrorError


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


def holder_path(driver, element):
    #a path to this image through whatever holds it. an image with nothing on it to match - a bare <img>
    #inside one div, with no id, class or alt - can still be reached through its container, and that path
    #finds every page on the address at once rather than only the one that was looked at.
    try:
        parent = element.find_element(By.XPATH, '..')
        tag = element.tag_name
    except se.WebDriverException:
        return None
    for name in ("id", "class"):
        try:
            value = parent.get_attribute(name)
        except se.WebDriverException:
            continue
        if value and '"' not in value:
            return '//*[@{0}="{1}"]/{2}'.format(name, value, tag)
    return None


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
                                 '//*[@class="{0}"]/img'.format(bits["class"]) if bits.get("class") else
                                 holder_path(driver, found))
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
    #a path through the container is the same path for every page on the address, so it would otherwise be
    #suggested once per image and fill the report with one answer written out five times
    seen, once = set(), []
    for bits in images:
        if bits.get("suggested") and bits["suggested"] in seen:
            continue
        seen.add(bits.get("suggested"))
        once.append(bits)
    return once[:5], links[:5]


def built_by_javascript(url, src):
    #whether the image is only in the page javascript builds. --check deliberately runs with javascript on,
    #so a path it reports as working can be one a scrape - which runs with it off - never sees. comparing
    #what the browser found against what the server actually sent is the whole of telling the two apart.
    try:
        body = fetch(url).text
    except (MirrorError, UnicodeDecodeError, ValueError):
        return None
    name = src.rsplit('/', 1)[-1].split('?')[0]
    return bool(name) and name not in body


def check_page(driver, element_names, next_ele_names):
    #every path that matches, in the order a scrape would try them, so it is clear which one would win
    found = {"url": driver.current_url, "title": driver.title, "image": [], "next": []}
    for element in element_names:
        srcs = ele_get_all(driver, element)
        if srcs:
            #how many pages the path finds here, so a comic serving several on one address is plain before
            #anything is downloaded rather than after the folder comes out a fraction of the size
            #the pages, worked out here rather than by whatever reads this: the rule for which of several
            #images is a page belongs in one place, and the web page should not have a second copy of it
            pages = comic_images(srcs, found["url"]) if len(srcs) > 1 else srcs
            found["image"].append({"xpath": element, "src": srcs[0], "count": len(srcs),
                                   "srcs": srcs[:20], "pages": pages[:20], "page_count": len(pages)})
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
    if found["image"]:
        found["needs_javascript"] = built_by_javascript(found["url"], found["image"][0]["src"])

    print("Checked {0}".format(found["url"]))
    for kind in ("image", "next"):
        if found[kind]:
            print("  {0}: {1} of the known paths match; a scrape would use {2}".format(
                kind, len(found[kind]), found[kind][0]["xpath"]))
            if kind == "image" and found[kind][0].get("count", 1) > 1:
                #worked out once, above, so this says the same as what the web page is handed
                top = found[kind][0]
                print("    that path finds {0} images here, {1} of them pages, so this address holds "
                      "several pages of the comic: {2}".format(
                          top["count"], top["page_count"],
                          ", ".join(src.rsplit('/', 1)[-1] for src in top["pages"][:6])))
            if kind == "image" and found.get("needs_javascript"):
                #the difference that makes a working path look like a broken one, since this check turns
                #javascript on and a scrape does not
                print("    that image is not in the page the server sends, only in the one javascript "
                      "builds, so this comic needs javascript as well as the path: -ej, or "
                      "\"javascript\": true in its settings.")
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
