"""A reader for the library the scraper keeps, in the browser, made to feel like a page-turning app.

It reads the library and never writes to it: the archives and loose pages are the scraper's, mounted
read-only, and everything the reader keeps - where each comic was read up to, thumbnails, what it learned
scanning - lives in its own data folder.

The rules for what a page is, the order pages read in and what an archive's ComicInfo says are the
scraper's own, imported from comiclib rather than copied, so the two can never disagree about which page
comes next.
"""
import os
import sys

#comiclib sits beside reader/ in the repo, and beside comicreader/ in the image. the repo's layout is
#tried when it is not already importable, so the tests and a local run need no install step
try:
    import comiclib  # noqa: F401
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
