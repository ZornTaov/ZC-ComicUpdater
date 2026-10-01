#the one queue every job goes through - an update, a check, working out chapters, adding comics - whoever
#asked for it: the page, the schedule or an update-now file. one at a time, so two never collide.
import collections
import itertools
import json
import os
import subprocess
import sys
import threading
import time
import traceback

from comiclib.batch import own_group
from comiclib.chapters.index import index_path, numbered_pages
from comiclib.metadata import METADATA_FILE, write_json


class LogTee:
    #everything update_comics prints still goes to the real output, so the container log is unchanged,
    #and the recent lines are also kept for the page to show
    def __init__(self, stream, keep=3000):
        self.stream = stream
        self.lines = collections.deque(maxlen=keep)
        self.seq = 0
        self.partial = ""
        self.lock = threading.Lock()

    def write(self, text):
        self.stream.write(text)
        with self.lock:
            self.partial += text
            *finished, self.partial = self.partial.split("\n")
            for line in finished:
                self.seq += 1
                self.lines.append((self.seq, time.time(), line))
        return len(text)

    def flush(self):
        self.stream.flush()

    def since(self, seq):
        with self.lock:
            return [line for line in self.lines if line[0] > seq], self.seq

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Job:
    counter = itertools.count(1)

    def __init__(self, kind, label, work):
        self.id = next(Job.counter)
        self.kind = kind
        self.label = label
        self.work = work
        self.created = time.time()
        self.started = None
        self.finished = None
        self.comics = []
        self.result = None
        self.error = None
        self.cancel = threading.Event()
        #what a check job found, read back by the page
        self.check = None
        #for a job that is one long step rather than a list of comics: the step running, and the last line
        #it said, so the page has something to show for a walk of thousands of pages
        self.process = None
        self.doing = None


class Runner:
    #one job at a time, whoever asked for it: the page, the schedule or an update-now file
    def __init__(self, args, uc):
        self.args = args
        self.uc = uc
        self.waiting = []
        self.current = None
        self.history = collections.deque(maxlen=25)
        self.next_run = None
        self.changed = threading.Condition()
        threading.Thread(target=self.loop, daemon=True, name="jobs").start()

    def submit(self, job):
        with self.changed:
            self.waiting.append(job)
            self.changed.notify_all()
        print("Queued: {0}".format(job.label), flush=True)
        return job

    def loop(self):
        while True:
            with self.changed:
                while not self.waiting:
                    self.changed.wait()
                job = self.waiting.pop(0)
                self.current = job
            job.started = time.time()
            try:
                job.result = job.work(job)
            except Exception as error:
                job.error = "{0}: {1}".format(type(error).__name__, error)
                print("ERROR: {0} failed: {1}".format(job.label, job.error), flush=True)
                traceback.print_exc(file=sys.stdout)
            job.finished = time.time()
            with self.changed:
                self.current = None
                self.history.appendleft(job)

    def stop(self):
        job = self.current
        if job is None:
            return False
        job.cancel.set()
        for comic in list(job.comics):
            if comic.process is not None and comic.code is None:
                comic.stopped = True
                self.uc.kill_tree(comic.process)
        if job.process is not None and job.process.poll() is None:
            self.uc.kill_tree(job.process)
        print("Stopping: {0}".format(job.label), flush=True)
        return True

    def drop(self, job_id):
        with self.changed:
            before = len(self.waiting)
            self.waiting = [job for job in self.waiting if job.id != job_id]
            return len(self.waiting) != before

    def submit_update(self, names, why):
        names = list(names or [])

        def work(job):
            chosen = self.uc.with_config(self.args)
            chosen.only = names or None
            chosen.dry_run = False
            chosen.cancel = job.cancel
            comics, runnable = self.uc.select_comics(chosen)
            job.comics = runnable
            if not runnable:
                return 0
            return self.uc.run_batch(comics, runnable, chosen)

        if not names:
            label = "{0}: every comic".format(why)
        elif len(names) <= 3:
            label = "{0}: {1}".format(why, ", ".join(names))
        else:
            label = "{0}: {1} comics".format(why, len(names))
        return self.submit(Job("update", label, work))

    def submit_check(self, url):
        #a browser is heavy enough that this waits its turn like everything else
        def work(job):
            command = [sys.executable, self.args.script, "--check", url]
            print("Checking {0}".format(url), flush=True)
            try:
                done = subprocess.run(command, cwd=self.args.root, capture_output=True, text=True,
                                      errors="replace", timeout=180,
                                      env=dict(os.environ, PYTHONUNBUFFERED="1"))
                output = (done.stdout or "") + (done.stderr or "")
            except subprocess.SubprocessError as error:
                job.check = {"error": str(error)}
                return 1
            for line in output.splitlines():
                if line.startswith("CHECK-JSON "):
                    job.check = json.loads(line[len("CHECK-JSON "):])
                    break
                print(line, flush=True)
            else:
                job.check = {"error": "the check said nothing useful", "output": output[-1500:]}
            return done.returncode

        return self.submit(Job("check", "Check {0}".format(url), work))

    def submit_chapterize(self, comic, listing, walk, every=None):
        uc = self.uc

        def work(job):
            args = uc.with_config(self.args)
            script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
            steps = []
            if every and walk == "start":
                #cutting by size needs only which file is which page, and numbered filenames say that
                #already: a comic of thousands of pages is spared an hour of walking, and its site the load
                job.doing = "reading the page numbers in its filenames ..."
                print("{0}: reading the page numbers in its filenames ...".format(comic.name), flush=True)
                _, why = numbered_pages(comic.folder)
                if why:
                    print("  they cannot say which page is which ({0}), so the comic is walked "
                          "first".format(why), flush=True)
                    steps.append(["index"])
                else:
                    print("  every file carries its page number, so it is cut from those without walking",
                          flush=True)
            elif walk:
                #nothing records which page is which yet, so the comic is walked once, downloading nothing.
                #a record that stops short is carried on from its last page rather than walked again
                steps.append(["index"])
            else:
                steps.append(["align"])
            if every:
                steps.append(["chapters", "--every", str(every), "--save"])
            else:
                steps.append(["chapters", "--archive", listing, "--save"] if listing
                             else ["chapters", "--urls", "--save"])
            if (comic.metadata.get("settings") or {}).get("cbz") is not False:
                steps.append(["pack", "--replace"])
            for step in steps:
                if job.cancel.is_set():
                    break
                print("{0}: {1} ...".format(comic.name, step[0]), flush=True)
                job.doing = "{0} ...".format(step[0])
                #read as it arrives, not all at the end: walking a comic of thousands of pages takes the
                #best part of an hour, and held back until it finished it looked like nothing was happening
                job.process = subprocess.Popen(
                    [sys.executable, script, step[0], comic.folder, "--root", args.root] + step[1:],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                    env=dict(os.environ, PYTHONUNBUFFERED="1"), **own_group())
                for line in job.process.stdout:
                    print("  " + line.rstrip(), flush=True)
                    if line.strip():
                        job.doing = "{0}: {1}".format(step[0], line.strip())
                code = job.process.wait()
                if job.cancel.is_set():
                    break
                if code != 0:
                    print("{0}: {1} stopped there. The pages are untouched.".format(comic.name, step[0]),
                          flush=True)
                    return code
            if job.cancel.is_set():
                #a walk stopped part way keeps every page it recorded, and the next one carries on from there
                print("{0}: stopped. The pages are untouched, and working the chapters out again carries on "
                      "from where it got to.".format(comic.name), flush=True)
                return self.uc.stopped_code
            return 0

        return self.submit(Job("chapters", "Work out chapters for {0}".format(comic.name), work))

    def submit_add(self, entries, options):
        uc = self.uc
        comics, listings, cuts = [], {}, {}
        for folder, cbz_path, url, listing in entries:
            settings = {
                "url": url,
                "output": folder,
                "cbz_path": cbz_path,
                "increment": options["increment"],
                "prefix": options["prefix"],
                "javascript": options["javascript"],
                "waittime": options["waittime"],
                #one switch: whether this comic keeps archives at all. a comic with chapters keeps one
                #per chapter instead of one of the lot, which mirror_base leaves to chapters.py
                "cbz": options["cbz"],
                "direction_check": options["direction_check"],
            }
            comic = uc.Comic(os.path.join(self.args.root, *folder.split("/")), {}, self.args.root)
            comic.argv = uc.settings_to_argv(settings)
            if options["prime"]:
                comic.argv.insert(0, "--prime")
            if listing or options.get("every"):
                #a comic that is going to be split into chapters records which page is which as it is
                #scraped, so it never has to be walked afterwards. a row's own chapter list wins over
                #cutting by size, since a comic's chapters come from one or the other
                comic.argv.insert(0, "--keep-index")
                if listing:
                    listings[comic.name] = listing
                else:
                    cuts[comic.name] = options["every"]
            comics.append(comic)

        def work(job):
            chosen = self.uc.with_config(self.args)
            chosen.cancel = job.cancel
            #a comic with a chapter list, or one to be cut by size, is told so before it is scraped, not
            #after: a scrape that does not know builds the single archive it will never want, and then
            #something has to go and delete it
            for comic in comics:
                if listings.get(comic.name) or cuts.get(comic.name):
                    remember_chapters(comic, listings.get(comic.name), cuts.get(comic.name), make_folder=True)
            #a new comic can be thousands of pages, so only priming keeps the usual limit. a stalled page
            #still ends on its own through mirror_base's page timeout, and anything else can be stopped here
            if not options["prime"]:
                chosen.timeout = 0
            job.comics = comics
            code = uc.run_batch(comics, comics, chosen, "Priming" if options["prime"] else "Scraping")
            for comic in comics:
                listing, every = listings.get(comic.name), cuts.get(comic.name)
                if not (listing or every):
                    continue
                if not comic.ok:
                    #a comic that saved nothing leaves nothing behind but the note we just wrote, which
                    #would otherwise make the folder look like a comic that is already in the library
                    if not uc.folder_pages(comic.folder):
                        try:
                            os.remove(os.path.join(comic.folder, METADATA_FILE))
                            os.rmdir(comic.folder)
                        except OSError:
                            pass
                    continue
                #a primed comic has one page and no chapters to find yet, so where they come from is written
                #down and the chapters are worked out by the update that fetches the rest
                remember_chapters(comic, listing, every)
                if not options["prime"]:
                    split_into_chapters(comic, listing, chosen, self.uc, options["cbz"], every)
            return code

        verb = "Prime" if options["prime"] else "Scrape"
        label = "{0} {1}".format(verb, comics[0].name if len(comics) == 1 else "{0} new comics".format(len(comics)))
        return self.submit(Job("add", label, work))


def remember_chapters(comic, listing, every=None, make_folder=False):
    #so a later run knows where this comic's chapters are listed, or how many pages go in each part,
    #whoever starts it
    path = os.path.join(comic.folder, METADATA_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (OSError, ValueError):
        if not make_folder:
            return
        #nothing there yet: the comic is about to be scraped for the first time
        os.makedirs(comic.folder, exist_ok=True)
        metadata = {}
    block = metadata.setdefault("chapters", {})
    if listing:
        if block.get("source_url") == listing:
            return
        block["source"] = "archive"
        block["source_url"] = listing
        said = "chapters will be read from {0}".format(listing)
    else:
        if block.get("every") == every:
            return
        #the same shape the edit form writes, so a comic cut from the start and one set to be cut later
        #are one kind of comic to everything that reads it
        block["source"], block["every"] = "every", every
        said = "will be cut into parts of {0} pages".format(every)
    block.setdefault("list", [])
    write_json(path, metadata)
    print("  {0}: {1}".format(comic.name, said), flush=True)


def remember_listing(comic, listing, make_folder=False):
    #its name before a comic could be cut by size as well, which code reaching in through web_ui still uses
    return remember_chapters(comic, listing, make_folder=make_folder)


def split_into_chapters(comic, listing, args, uc, keeps_archives=True, every=None):
    #a new comic that was given a chapter list, or a size to cut it at: line up what was just saved, work
    #the chapters out, and write one archive per chapter. every step says what it did, and none of them
    #touches the pages themselves.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    if not os.path.exists(script):
        return
    #a comic added from part way in keeps no index, since one begun there would number its pages wrong.
    #cut by size, its numbered filenames say which page is which instead, and there is nothing to line up
    steps = [["align"]] if not every or os.path.exists(index_path(comic.folder, args.root)) else []
    steps.append(["chapters", "--every", str(every), "--save"] if every
                 else ["chapters", "--archive", listing, "--save"])
    #--replace because a comic kept in chapters keeps no single archive: the one the scrape just built
    #is given up as soon as every page is checked to be in a chapter
    if keeps_archives:
        steps.append(["pack", "--replace"])
    for step in steps:
        done = subprocess.run([sys.executable, script, step[0], comic.folder, "--root", args.root]
                              + step[1:], capture_output=True, text=True, errors="replace",
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=1800)
        said = (done.stdout or done.stderr or "").strip().splitlines()
        print("  {0}: {1}".format(step[0], said[-1][:120] if said else "exit {0}".format(done.returncode)),
              flush=True)
        if done.returncode != 0:
            print("  {0} stopped there, so its chapters were not written. The pages are saved either "
                  "way.".format(comic.name), flush=True)
            return
