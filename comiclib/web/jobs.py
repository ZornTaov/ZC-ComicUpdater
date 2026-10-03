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
import zipfile

from comiclib.batch import own_group
from comiclib.chapters.index import index_path, numbering_trouble, set_aside, set_aside_pages
from comiclib.exits import USAGE
from comiclib.metadata import METADATA_FILE, write_json
from comiclib.paths import config_folder
from comiclib.web.uploads import Refused, mark_queued, place
from comiclib.web.views import chapters_label, job_view

#how far back the page's Recent list reaches. it is kept in the config folder, so a restart - which a
#restart file makes routine - does not empty it; and capped by count too, against a week of something
#queued over and over
recent_days = 7
recent_most = 1000


def recent_path():
    return os.path.join(config_folder(), "recent.json")


def load_recent():
    #what finished in the last week, newest first, as the page was shown it when it finished
    path = recent_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            held = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        print("WARNING: could not read {0}, so Recent starts empty: {1}".format(path, error), flush=True)
        return []
    return within_week(held if isinstance(held, list) else [])


def within_week(entries):
    since = time.time() - recent_days * 86400
    return [entry for entry in entries
            if isinstance(entry, dict) and (entry.get("finished") or 0) >= since][:recent_most]


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
        #why working out chapters stopped short of doing anything, and what the reader can choose to do
        #about it, which the page offers in the comic's editor
        self.decide = None
        #what a job that is not about scraping did, in a sentence, for Recent: an upload put in the library
        self.outcome = None


class Runner:
    #one job at a time, whoever asked for it: the page, the schedule or an update-now file
    def __init__(self, args, uc):
        self.args = args
        self.uc = uc
        self.waiting = []
        self.current = None
        #what the page shows under Recent: each job as it was shown the moment it finished, newest first
        self.recent = load_recent()
        self.saving = threading.Lock()
        #numbered on from the last week's, so a job from before a restart and one after never share a
        #number - the page tells finished jobs apart by it
        Job.counter = itertools.count(max([entry.get("id") for entry in self.recent
                                           if isinstance(entry.get("id"), int)] or [0]) + 1)
        self.next_run = None
        self.changed = threading.Condition()
        #set while the process is about to exit for a restart: a job queued then waits rather than starting
        #a scrape the exit would cut off part way
        self.closed = False
        threading.Thread(target=self.loop, daemon=True, name="jobs").start()

    def close_if_idle(self):
        #closed in the same step that finds nothing running and nothing waiting, so nothing slips in between
        with self.changed:
            if self.current is not None or self.waiting:
                return False
            self.closed = True
            return True

    def reopen(self):
        with self.changed:
            self.closed = False
            self.changed.notify_all()

    def submit(self, job):
        with self.changed:
            self.waiting.append(job)
            self.changed.notify_all()
        print("Queued: {0}".format(job.label), flush=True)
        return job

    def loop(self):
        while True:
            with self.changed:
                while not self.waiting or self.closed:
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
            try:
                view = job_view(job, self.uc)
            except Exception as error:
                #a summary that will not build is no reason for the queue to stop: the job ran either way
                view = {"id": job.id, "kind": job.kind, "label": job.label, "started": job.started,
                        "finished": job.finished, "error": job.error or "could not summarise: {0}".format(error)}
            with self.changed:
                self.current = None
            self.remember(view)

    def remember(self, view):
        #added to Recent and written out at once, so a restart a moment later still shows it
        with self.changed:
            self.recent = within_week([view] + self.recent)
            kept = list(self.recent)
        with self.saving:
            try:
                write_json(recent_path(), kept, indent=None)
            except OSError as error:
                print("WARNING: could not save Recent to {0}: {1}".format(recent_path(), error), flush=True)

    def note(self, kind, label):
        #something that happened that was not a job - a restart - shown under Recent among the jobs
        at = time.time()
        self.remember({"id": next(Job.counter), "kind": kind, "label": label, "created": at,
                       "started": at, "finished": at})

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

    def submit_chapterize(self, comic, listing, walk, every=None, choices=None):
        uc = self.uc
        choices = choices or {}

        def work(job):
            args = uc.with_config(self.args)
            script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
            steps = []
            if every and walk == "start":
                #what the reader chose when this stopped short last time, done first and said out loud
                cache = index_path(comic.folder, args.root)
                if choices.get("discard_walk"):
                    for old, new in set_aside(cache):
                        print("{0}: moved {1} aside as {2}, as asked".format(
                            comic.name, os.path.basename(old), os.path.basename(new)), flush=True)
                if choices.get("set_aside"):
                    moved, refused = set_aside_pages(comic.folder, choices["set_aside"])
                    for name, where in moved:
                        print("{0}: set {1} aside, in {2}".format(comic.name, name, where), flush=True)
                    for name, why in refused:
                        print("{0}: left {1} where it is: {2}".format(comic.name, name, why), flush=True)
                if choices.get("walk"):
                    print("{0}: walking it, as asked".format(comic.name), flush=True)
                    steps.append(["index"])
                else:
                    #cutting by size needs only which file is which page, and numbered filenames say that
                    #already: a comic of thousands of pages is spared an hour of walking, and its site the
                    #load. when they cannot say, the reader decides what happens next rather than this
                    #walking on its own: a walk can be an hour, can fail on a site whose first-page link is
                    #broken, and leaves a record behind that then stands in the way of the numbers
                    job.doing = "reading the page numbers in its filenames ..."
                    print("{0}: reading the page numbers in its filenames ...".format(comic.name), flush=True)
                    trouble = numbering_trouble(comic.folder, cache)
                    if trouble:
                        trouble["comic"] = comic.name
                        trouble["every"] = every
                        job.decide = trouble
                        print("  they cannot say which page is which: {0}. Nothing was walked or changed; the "
                              "comic's editor says what can be done about it.".format(trouble["why"]), flush=True)
                        return USAGE
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

        return self.submit(Job("chapters", chapters_label(comic.name), work))

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


    def submit_place(self, chosen):
        #an upload put into the library: in the queue like everything else, so it never unpacks into a folder
        #a scrape is writing to, or replaces a comic part way through being updated
        uc = self.uc

        def every_pages(folder, every):
            remember_chapters(uc.Comic(folder, {}, self.args.root), None, every)

        def work(job):
            try:
                job.outcome = place(chosen, uc.with_config(self.args), every_pages, job.cancel)
            except (Refused, OSError, zipfile.BadZipFile) as error:
                job.error = str(error)
                print("ERROR: {0}: {1}".format(job.label, error), flush=True)
                #offered again, so it can be tried another way rather than uploaded afresh
                mark_queued(self.args.root, chosen["id"], False)
                return 1
            print("{0}: {1}".format(job.label, job.outcome), flush=True)
            return 0

        mark_queued(self.args.root, chosen["id"], True)
        return self.submit(Job("upload", "Upload {0}".format(chosen["pages_at"]), work))


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
