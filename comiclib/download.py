#fetching a page's image. the browser is only ever asked where the image is; the bytes come from here.
from time import sleep

import requests

from comiclib.exits import DOWNLOAD as EXIT_DOWNLOAD, MirrorError

#set by the scrape from its --verbose, for saying each retry out loud
verbose = False


def fetch(url, attempts=3, referer=None):
    #retries briefly so a blip does not end an unattended run, then gives up loudly rather than
    #writing an error page to disk under an image filename. referer is the page the image was shown on,
    #for a site that refuses its pictures to anyone who did not come from one of its own pages
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(1, attempts + 1):
        try:
            req = requests.get(url, stream=True, timeout=30, headers=headers)
            if req.status_code != 200:
                raise requests.RequestException("HTTP {0}".format(req.status_code))
            return req
        except requests.RequestException as error:
            if attempt == attempts:
                raise MirrorError("Could not download {0}: {1}".format(url, error), EXIT_DOWNLOAD, "download failed")
            if verbose: print("\nAttempt {0} for {1} failed ({2}); retrying.".format(attempt, url, error))
            sleep(2 * attempt)
