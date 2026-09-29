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

    def submit_chapterize(self, comic, listing, walk):
        uc = self.uc

        def work(job):
            args = uc.with_config(self.args)
            script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
            steps = []
            if walk:
                #nothing records which page is which yet, so the comic is walked once, downloading nothing
                steps.append(["index"])
            else:
                steps.append(["align"])
            steps.append(["chapters", "--archive", listing, "--save"] if listing
                         else ["chapters", "--urls", "--save"])
            if (comic.metadata.get("settings") or {}).get("cbz") is not False:
                steps.append(["pack", "--replace"])
            for step in steps:
                print("{0}: {1} ...".format(comic.name, step[0]), flush=True)
                done = subprocess.run([sys.executable, script, step[0], comic.folder, "--root", args.root]
                                      + step[1:], capture_output=True, text=True, errors="replace",
                                      env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=None)
                for line in (done.stdout or "").splitlines():
                    print("  " + line, flush=True)
                if done.returncode != 0:
                    print("{0}: {1} stopped there. The pages are untouched.".format(comic.name, step[0]),
                          flush=True)
                    return done.returncode
            return 0

        return self.submit(Job("chapters", "Work out chapters for {0}".format(comic.name), work))

    def submit_add(self, entries, options):
        uc = self.uc
        comics, listings = [], {}
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
            if listing:
                #a comic that is going to be split into chapters records which page is which as it is
                #scraped, so it never has to be walked afterwards
                comic.argv.insert(0, "--keep-index")
                listings[comic.name] = listing
            comics.append(comic)

        def work(job):
            chosen = self.uc.with_config(self.args)
            chosen.cancel = job.cancel
            #a comic with a chapter list is told so before it is scraped, not after: a scrape that does not
            #know builds the single archive it will never want, and then something has to go and delete it
            for comic in comics:
                if listings.get(comic.name):
                    remember_listing(comic, listings[comic.name], make_folder=True)
            #a new comic can be thousands of pages, so only priming keeps the usual limit. a stalled page
            #still ends on its own through mirror_base's page timeout, and anything else can be stopped here
            if not options["prime"]:
                chosen.timeout = 0
            job.comics = comics
            code = uc.run_batch(comics, comics, chosen, "Priming" if options["prime"] else "Scraping")
            for comic in comics:
                if not listings.get(comic.name):
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
                #a primed comic has one page and no chapters to find yet, so the archive page is written
                #down and the chapters are worked out by the update that fetches the rest
                remember_listing(comic, listings[comic.name])
                if not options["prime"]:
                    split_into_chapters(comic, listings[comic.name], chosen, self.uc, options["cbz"])
            return code

        verb = "Prime" if options["prime"] else "Scrape"
        label = "{0} {1}".format(verb, comics[0].name if len(comics) == 1 else "{0} new comics".format(len(comics)))
        return self.submit(Job("add", label, work))


def remember_listing(comic, listing, make_folder=False):
    #so a later run knows where this comic's chapters are listed, whoever starts it
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
    if block.get("source_url") == listing:
        return
    block["source"] = "archive"
    block["source_url"] = listing
    block.setdefault("list", [])
    write_json(path, metadata)
    print("  {0}: chapters will be read from {1}".format(comic.name, listing), flush=True)


def split_into_chapters(comic, listing, args, uc, keeps_archives=True):
    #a new comic that was given a chapter list: line up what was just saved, read the list, and write one
    #archive per chapter. every step says what it did, and none of them touches the pages themselves.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    if not os.path.exists(script):
        return
    #--replace because a comic kept in chapters keeps no single archive: the one the scrape just built
    #is given up as soon as every page is checked to be in a chapter
    steps = [["align"], ["chapters", "--archive", listing, "--save"]]
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
