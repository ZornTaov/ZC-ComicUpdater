#telling one page's address from another's, and a page of the comic from everything else a site links to.
import re
from urllib.parse import urljoin


def same_page(url):
    #one page can be written several ways - http or https, with or without www or a trailing slash - so
    #everything is reduced to the part that actually identifies it before anything is compared
    url = (url or "").strip()
    url = re.sub(r'^https?://', '', url, flags=re.I)
    url = re.sub(r'^www\.', '', url, flags=re.I)
    return url.rstrip('/').lower()


def says_it_twice(url):
    #a path with the same step twice in a row, which is what a mis-joined relative link looks like
    steps = same_page(url or "").partition('?')[0].split('/')
    return 1 if any(one and one == next_one for one, next_one in zip(steps, steps[1:])) else 0


def link_targets(base, href):
    #where a link points, allowing for the two ways an archive writes one. a dropdown's value is what its
    #script navigates to, and such values are usually written from the site's root rather than from the
    #page's own folder - "mycomic/first-day" on a page that already sits in /mycomic/. both readings are
    #offered and whichever is a page of the comic is the one meant.
    here = urljoin(base, href)
    from_root = urljoin(urljoin(base, '/'), href.lstrip('/'))
    if here == from_root:
        return [here]
    #joining "mycomic/first-day" onto a page already inside /mycomic/ says it twice, and no
    #site has a path like that. so a reading that repeats a step is tried last, not first.
    return sorted([here, from_root], key=says_it_twice)


def looks_like_pages(url, known):
    #without an index nothing knows this comic's addresses, so a link counts as a page when it sits on the
    #same site and under the same part of the path as the page the comic is known to be on
    def parts(where):
        site, _, rest = same_page(where or "").partition('/')
        path = rest.partition('?')[0]
        return site, (path.split('/')[0] if path else '')

    site, first = parts(known)
    where, theirs = parts(url)
    if not site or where != site:
        return False
    #the same first step of the path: /comic/... for one comic, index.php?pid=... for another. a link to
    #the archive itself, or to some other page of the site, is not a page of the comic.
    if theirs == first:
        #the first step on its own, when the comic's pages go further: /comic beside /comic/2004-02-22 is
        #the comic's front page, which shows whichever page is newest and so is none of them in particular
        bare = same_page(url).partition('/')[2]
        return bare != first or bare == same_page(known).partition('/')[2]
    #or the same shape, for a comic that puts the chapter in the first step and so has no fixed one:
    #/c1/p1, /c2/p1, /c12.1/p1 are all the same kind of address, and archive.html is not.
    return bool(re.match(page_shape(known), same_page(url).partition('?')[0]))


def page_shape(known):
    #the address with every run of digits (and the dots inside them) made a wildcard, so one page of a
    #comic describes the rest: c1/p1 becomes c<number>/p<number>
    plain = same_page(known or "").partition('?')[0]
    return "".join("[0-9.]+" if bit[0].isdigit() else re.escape(bit)
                   for bit in re.findall(r'\d[\d.]*|\D+', plain)) + "$"


def page_at(pages, where):
    #which page an address is. a fix names its page this way because an address does not change when
    #pages are added before it, while a page number does
    want = same_page(str(where or ""))
    for page in pages:
        if same_page(page["url"]) == want:
            return page["n"]
    return None
