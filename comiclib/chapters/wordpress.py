#the record of which page is which, read from a WordPress site's own list of its posts rather than walked.
#a comic on WordPress answers /wp-json/ with every post of a type, in date order, each with its address
#and the image it features - which is everything a walk records, for a hundred pages a request instead of
#one page a browser load. a comic of eight thousand pages is listed in a couple of minutes.
#
#what it cannot know is what the next link does: the list is in the order posts were dated, which is the
#order a comic's next link follows on every theme that builds one from the dates, and a page the site never
#posted - an image uploaded and linked from nowhere - is in neither. the sizes the alignment asks for
#afterwards are what say whether the two agree.
import html
import os
import re
from urllib.parse import urlsplit

import requests

from comiclib.chapters.index import index_path, patiently, read_index, set_aside, write_lines
from comiclib.metadata import read as read_metadata
from comiclib.pages import saved_name

#the most posts the api hands out in one answer
PER_PAGE = 100
#the post types every WordPress site has, which are never a comic's own: tried last, if at all
BUILT_IN = {"page", "attachment", "nav_menu_item", "wp_block", "wp_template", "wp_template_part",
            "wp_global_styles", "wp_navigation", "wp_font_family", "wp_font_face"}
#the first image in a post's body, for a post that features none and carries its page in the text instead
BODY_IMAGE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)


class NotWordPress(Exception):
    #why this comic's site cannot list its pages, said so the reader knows to walk it instead
    pass


def start_address(folder, args):
    #any one page of the comic will do: the list is of all of them, so it does not matter which
    metadata = read_metadata(folder)
    history = metadata.get("history") or {}
    return (args.start or getattr(args, "like", None) or history.get("first_page_url")
            or (metadata.get("settings") or {}).get("url"))


def api_root(session, address):
    #where the site's api lives. /wp-json/ almost always; a site without pretty addresses names it in a
    #<link rel="https://api.w.org/"> on every page instead, which is asked for only when the first fails
    parts = urlsplit(address)
    guess = "{0}://{1}/wp-json/".format(parts.scheme, parts.netloc)
    try:
        answer = patiently(session.get, guess, timeout=60)
        if answer.ok and answer.headers.get("Content-Type", "").startswith("application/json"):
            return guess
        page = patiently(session.get, address, timeout=60)
    except requests.RequestException as error:
        raise NotWordPress("could not reach {0}: {1}".format(address, error))
    found = re.search(r'<link[^>]+rel=["\']https://api\.w\.org/["\'][^>]+href=["\']([^"\']+)', page.text)
    if not found:
        raise NotWordPress("{0} does not answer as a WordPress site does".format(address))
    return html.unescape(found.group(1))


def endpoint(root, route):
    #/wp-json/ takes the route as a path, and ?rest_route=/ as the end of a parameter: either way, it goes on
    #after the root's last slash
    return root.rstrip("/") + "/" + route


def ask(session, root, route, params=None):
    answer = patiently(session.get, endpoint(root, route), params=params, timeout=120)
    answer.raise_for_status()
    return answer


def post_type(session, root, address):
    #which of the site's post types this comic is: the one whose list holds the page the comic was given.
    #a comic theme usually serves its pages at /comic/<slug>/ from a type called comic, so the first part
    #of the address is tried first; failing that every type the site offers is asked for that slug
    path = [bit for bit in urlsplit(address).path.split("/") if bit]
    if not path:
        raise NotWordPress("{0} is the site's front page, not one of the comic's pages".format(address))
    slug = path[-1]
    try:
        types = ask(session, root, "wp/v2/types").json()
    except (requests.RequestException, ValueError) as error:
        raise NotWordPress("the site would not list its post types: {0}".format(error))
    bases = []
    for name, kind in types.items():
        base = kind.get("rest_base") if isinstance(kind, dict) else None
        if base and name not in BUILT_IN and "(" not in base:
            bases.append((0 if path[0] in (name, base) else 1 if name == "post" else 2, base))
    for _, base in sorted(bases):
        try:
            held = ask(session, root, "wp/v2/" + base, {"slug": slug, "_fields": "id,link"}).json()
        except (requests.RequestException, ValueError):
            continue
        if isinstance(held, list) and held:
            return base
    raise NotWordPress("none of the site's post types holds {0}".format(address))


def all_posts(session, root, base):
    #every post of the type, a hundred at a time. the order is put right afterwards rather than trusted to
    #the api: two posts on one date come back in whichever order the database likes
    fields = "id,date,link,title,featured_media"
    posts, page, pages = [], 1, None
    while pages is None or page <= pages:
        answer = ask(session, root, "wp/v2/" + base, {"per_page": PER_PAGE, "page": page, "orderby": "date",
                                                      "order": "asc", "_fields": fields})
        pages = int(answer.headers.get("X-WP-TotalPages") or 1)
        posts += answer.json()
        if page % 10 == 0 or page == pages:
            print("  listed {0} of {1} post(s)".format(len(posts), answer.headers.get("X-WP-Total") or "?"),
                  flush=True)
        page += 1
    #the date and then the id, which counts up in the order posts were made
    return sorted(posts, key=lambda post: (post.get("date") or "", post.get("id") or 0))


def images(session, root, base, posts):
    #the image each post features, asked for a hundred at a time. a post featuring none may carry its page
    #in its body instead, as older comic themes did, so those posts' bodies are read for their first image
    featured = sorted({post["featured_media"] for post in posts if post.get("featured_media")})
    found = {}
    for at in range(0, len(featured), PER_PAGE):
        chunk = featured[at:at + PER_PAGE]
        for media in ask(session, root, "wp/v2/media", {"include": ",".join(map(str, chunk)),
                                                        "per_page": PER_PAGE, "_fields": "id,source_url"}).json():
            found[media["id"]] = media.get("source_url")
    bare = [post for post in posts if not found.get(post.get("featured_media"))]
    body = {}
    for at in range(0, len(bare), PER_PAGE):
        chunk = [post["id"] for post in bare[at:at + PER_PAGE]]
        for post in ask(session, root, "wp/v2/" + base, {"include": ",".join(map(str, chunk)),
                                                         "per_page": PER_PAGE, "_fields": "id,content"}).json():
            image = BODY_IMAGE.search(((post.get("content") or {}).get("rendered")) or "")
            if image:
                body[post["id"]] = html.unescape(image.group(1))
    return {post["id"]: found.get(post.get("featured_media")) or body.get(post["id"]) for post in posts}


def wordpress_index(folder, args):
    #the index a walk would have written, from the site's list of its posts. the path written, or None
    cache = index_path(folder, args.root, args)
    if os.path.exists(cache) and os.path.getsize(cache):
        if not getattr(args, "restart", False):
            print("ERROR: {0} already holds {1} page(s). Pass --restart to set it aside and list the comic "
                  "afresh.".format(cache, len(read_index(cache))))
            return None
        for was, now in set_aside(cache):
            print("Moved {0} aside as {1}.".format(os.path.basename(was), os.path.basename(now)))
    address = start_address(folder, args)
    if not address:
        print("ERROR: nothing says where {0} is on the web. Pass --start with any one of its pages.".format(folder))
        return None
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        root = api_root(session, address)
        base = post_type(session, root, address)
        print("Listing the comic from {0}wp/v2/{1} ...".format(root, base), flush=True)
        posts = all_posts(session, root, base)
        srcs = images(session, root, base, posts)
    except NotWordPress as error:
        print("ERROR: {0}. Walk it instead: chapters.py index {1}".format(error, folder))
        return None
    except (requests.RequestException, ValueError) as error:
        print("ERROR: the site stopped answering part way through listing the comic: {0}. Nothing was "
              "written; running it again starts over.".format(error))
        return None
    lines, seen, twice = [], set(), []
    for post in posts:
        src = srcs.get(post["id"])
        #one image featured by two posts is one page posted twice - a strip put up again under /<date>-2/ -
        #and two lines for it would leave one file for two pages, which nothing can settle. the first stays
        if src and src.split("?")[0] in seen:
            twice.append(post.get("link"))
            continue
        if src:
            seen.add(src.split("?")[0])
        lines.append({"n": len(lines) + 1, "url": post.get("link"), "src": src,
                      "file": saved_name(src) if src else None,
                      "title": html.unescape(((post.get("title") or {}).get("rendered")) or ""), "bytes": None})
    if twice:
        print("Left out {0} post(s) featuring an image an earlier post already does, as the same page posted "
              "again: {1}{2}".format(len(twice), twice[:3], "..." if len(twice) > 3 else ""))
    os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
    write_lines(cache, lines)
    imageless = sum(1 for line in lines if not line["src"])
    print("Index holds {0} pages from the site's own list{1}, written to {2}".format(
        len(lines), ", {0} of them with no image".format(imageless) if imageless else "", cache), flush=True)
    return cache
