#what mirror_base's exit code means. a batch reads it to tell an ordinary update from a site that broke, so
#the numbers are a contract: never reuse one for something else.
OK = 0
INTERRUPTED = 1
USAGE = 2
NO_IMAGE = 3
DOWNLOAD = 4
DRIVER = 5
TIMEOUT = 6
UNEXPECTED = 7
BACKWARDS = 8
SAME_NAMES = 9
SKIPS = 10

class MirrorError(Exception):
    #a scrape failure that should end the run with a specific exit code
    def __init__(self, message, code, reason):
        super().__init__(message)
        self.code = code
        self.reason = reason


#what update_comics says about each in its summary
REASONS = {
    OK: "up to date",
    INTERRUPTED: "interrupted",
    USAGE: "bad arguments",
    NO_IMAGE: "image element not found (site layout changed?)",
    DOWNLOAD: "download failed",
    DRIVER: "webdriver would not start",
    TIMEOUT: "page load timed out (slow or unresponsive site)",
    UNEXPECTED: "unexpected error",
    BACKWARDS: "next link runs backwards (check the site's next element)",
    SAME_NAMES: "the site reuses image names between chapters; this comic needs prefix turned on",
    SKIPS: "next link skips pages the comic's record lists (check the site's next element)",
}
