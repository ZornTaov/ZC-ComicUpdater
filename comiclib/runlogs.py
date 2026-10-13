#each comic's own output from an update, kept a file per run. the page's log is the updater's summary, and
#everything a scrape or a plugin's program said along the way - which chapter it was on, why it gave up - was
#read off its pipe for the page's last line and thrown away once it finished. a week of them is kept, as
#long as Recent remembers the job that ran it.
import codecs
import locale
import os
import re
import shlex
import subprocess
import threading
import time

from comiclib.paths import config_folder

keep_days = 7
SUFFIX = ".log"
#what the page is handed a log as
KIND = "text/plain; charset=utf-8"


def logs_folder():
    #MIRROR_LOGS names it outright, which is how a test keeps its own; otherwise beside the config folder,
    #which in the container is the mounted folder, so the logs outlive a restart and can be read off the share
    named = os.environ.get("MIRROR_LOGS")
    return os.path.abspath(named or os.path.join(os.path.dirname(os.path.abspath(config_folder())), "logs"))


def comic_folder(name):
    #a comic's logs under its path within the library, so they can be found by eye. each part made safe for
    #windows as well, whose names cannot hold some of what a folder on the nas can, or end in a dot
    parts = [re.sub(r'[<>:"\\|?*\x00-\x1f]', "_", part).rstrip(" .") or "_"
             for part in name.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    return os.path.join(logs_folder(), *(parts or ["_"]))


def shown(command):
    return shlex.join(command) if os.name != "nt" else subprocess.list2cmdline(command)


class RunLog:
    #one comic's run, written as it goes so a run still going can be read, and so a run killed part way
    #leaves what it got to. a log that cannot be written never stops the run: problem says why, once
    def __init__(self, name, command):
        self.started = time.time()
        self.path = None
        self.problem = None
        self.file = None
        self.lock = threading.Lock()
        folder = comic_folder(name)
        stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(self.started))
        try:
            os.makedirs(folder, exist_ok=True)
            #a comic stopped and started again within the second keeps both
            for n in range(1, 100):
                path = os.path.join(folder, stamp + ("" if n == 1 else "_{0}".format(n)) + SUFFIX)
                try:
                    self.file = open(path, "x", encoding="utf-8", errors="replace", newline="\n")
                except FileExistsError:
                    continue
                self.path = path
                break
        except OSError as error:
            self.problem = str(error)
            return
        self.write("# {0}".format(name), "# started {0}".format(time.strftime("%Y-%m-%d %H:%M:%S %Z",
                                                                             time.localtime(self.started))),
                   "# " + shown(command), "")

    @property
    def name(self):
        #what the page asks for it by: its path within the logs folder
        if not self.path:
            return None
        return os.path.relpath(self.path, logs_folder()).replace(os.sep, "/")

    def write(self, *lines):
        with self.lock:
            if self.file is None:
                return
            try:
                self.file.write("".join(line + "\n" for line in lines))
                self.file.flush()
            except OSError as error:
                self.problem = str(error)
                self.close_file()

    def section(self, title):
        #a step after the scrape, its chapters worked on, set apart from what the scrape said
        self.write("", "--- {0} ---".format(title))

    def close(self, ended):
        self.write("", "# ended {0}: {1}, after {2:.0f}s".format(
            time.strftime("%H:%M:%S", time.localtime()), ended, time.time() - self.started))
        with self.lock:
            self.close_file()

    def close_file(self):
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None


def follow(stream, on_line, on_showing):
    #a program's output read as it comes, from a binary stream. a line ended by \n is finished. one ended
    #by \r is a progress bar drawing itself again, so only its last state is kept, as a terminal would show
    #it. and what has come of a line that has no ending yet is shown too: a bar drawn as "\r" + the bar is
    #never ended until the next one is drawn, so the page would always be a step behind
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace")
    read = getattr(stream, "read1", stream.read)
    held, redrawn = "", None

    def ended(text, end):
        nonlocal redrawn
        if end == "\r":
            if text:
                redrawn = text
                on_showing(text)
            return
        #\r\n, or a bar finished by a bare print(): the bar as it was last drawn is the line
        if not text and redrawn is not None:
            text = redrawn
        redrawn = None
        on_line(text)

    while True:
        chunk = read(65536)
        if not chunk:
            break
        pieces = re.split(r"([\r\n])", held + decoder.decode(chunk))
        held = pieces.pop()
        for text, end in zip(pieces[0::2], pieces[1::2]):
            ended(text, end)
        if held:
            on_showing(held)
    held += decoder.decode(b"", final=True)
    if held or redrawn is not None:
        on_line(held or redrawn)


def listing(name):
    #a comic's logs, newest first, for its editor
    folder = comic_folder(name)
    try:
        found = [entry for entry in os.scandir(folder) if entry.is_file() and entry.name.endswith(SUFFIX)]
    except OSError:
        return []
    found.sort(key=lambda entry: entry.name, reverse=True)
    return [{"name": os.path.relpath(entry.path, logs_folder()).replace(os.sep, "/"),
             "at": entry.stat().st_mtime, "size": entry.stat().st_size} for entry in found]


def prune(now=None):
    #a week's worth, and the folders of comics with none left - one moved, renamed or deleted - gone with them
    folder = logs_folder()
    since = (now or time.time()) - keep_days * 86400
    for where, folders, files in os.walk(folder, topdown=False):
        for name in files:
            path = os.path.join(where, name)
            try:
                if name.endswith(SUFFIX) and os.path.getmtime(path) < since:
                    os.remove(path)
            except OSError:
                pass
        if where != folder:
            try:
                os.rmdir(where)
            except OSError:
                pass
