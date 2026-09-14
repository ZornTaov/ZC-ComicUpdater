#runs mirror_base.py over every comic in a library folder, resuming each one from its saved metadata.
#meant to be driven by a timer, so it isolates failures, caps how long any one comic can run, and finishes
#with a summary of what moved. #V 1.3

import argparse
import copy
import fnmatch
import json
import os
import shlex
import signal
import subprocess
import threading
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

metadata_file = "mirror_metadata.json"
#a comic marked this way is meant to be left alone for good, so it is counted rather than listed.
#anything skipped for any other reason is a problem, and gets named.
ended_reason = "marked as ended"
#print() writes its text and its newline separately, so two comics finishing at once could tear each
#other's lines in half. everything a worker prints goes through here instead: one line, one write.
print_lock = threading.Lock()


def say(line):
    with print_lock:
        sys.stdout.write(line + chr(10))
        sys.stdout.flush()


lock_file = ".update_comics.lock"
#dropping a file of this name into the library root starts an update without waiting for the schedule,
#which is the whole interface a container needs: anything that can reach the share can make the file.
#either spelling counts, since windows hides the extension on a new text document
trigger_files = ("update-now", "update-now.txt")
#how often a scheduled wait looks for one
trigger_poll = 30

#mirror_base's exit codes, so the summary can say what actually went wrong
exit_reasons = {
    0: "up to date",
    1: "interrupted",
    2: "bad arguments",
    3: "image element not found (site layout changed?)",
    4: "download failed",
    5: "webdriver would not start",
    6: "page load timed out (slow or unresponsive site)",
    7: "unexpected error",
    8: "next link runs backwards (check the site's next element)",
}


def folder_pages(folder):
    try:
        return len([f for f in os.listdir(folder) if f != metadata_file])
    except OSError:
        return 0


class Comic:
    #one folder holding pages, its metadata and the result of this run
    def __init__(self, folder, metadata, root=None):
        self.folder = folder
        #named by its path within the library, so grouped comics stay distinguishable in the summary
        self.name = os.path.relpath(folder, root).replace(os.sep, '/') if root else os.path.basename(folder)
        self.metadata = metadata
        self.argv = None
        self.code = None
        self.output = ""
        self.elapsed = 0.0
        #metadata written before page_count existed has no baseline, so count the folder instead of
        #treating it as empty and reporting the whole comic as newly gained
        count = (metadata.get("state") or {}).get("page_count", metadata.get("page_count"))
        if count is None:
            count = folder_pages(folder)
        self.before = count or 0
        self.after = self.before
        self.skipped = None
        #when this comic's process started, so a run in progress can say what it is still waiting on
        self.started_at = None
        #set when the saved command pointed at where this comic used to live
        self.moved_from = None

    @property
    def gained(self):
        return max(self.after - self.before, 0)

    @property
    def ok(self):
        return self.code == 0


def find_comics(root, max_depth=5):
    #a comic is any folder holding a metadata file, so adding one is just scraping or adopting it once.
    #the search goes down through grouping folders, since a library often sorts comics by author or site,
    #but never descends past a comic: whatever a comic keeps inside it is its own business.
    comics = []
    root = os.path.abspath(root)
    for current, dirs, files in os.walk(root):
        depth = current[len(root):].count(os.sep)
        if metadata_file in files:
            dirs[:] = []
            meta_path = os.path.join(current, metadata_file)
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    comics.append(Comic(current, json.load(f), root))
            except (ValueError, OSError) as error:
                comic = Comic(current, {}, root)
                comic.skipped = "unreadable metadata: {0}".format(error)
                comics.append(comic)
            continue
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
    return sorted(comics, key=lambda c: c.name)


def settings_to_argv(settings):
    #the single place a scrape command is built. the metadata file records what a comic needs as plain
    #values, not as a command, so this is the only thing that has to know which value is which flag -
    #and editing one value in the file is the whole of changing how a comic is scraped.
    url = settings.get("url")
    if not url:
        return None
    argv = []
    if settings.get("increment") is not None:
        argv += ["--increment", str(settings["increment"])]
    if settings.get("output"):
        argv += ["--output", settings["output"]]
    if settings.get("prefix"):
        argv.append("--prefix")
    if settings.get("javascript"):
        argv.append("--enable_javascript")
    if settings.get("firefox"):
        argv.append("--firefox")
    if settings.get("waittime"):
        argv += ["--waittime", str(settings["waittime"])]
    #on by default, so only its absence is worth saying out loud
    if settings.get("cbz") is False:
        argv.append("--no-cbz")
    #also on by default, so only turning it off is worth saying
    if settings.get("direction_check") is False:
        argv.append("--no-direction-check")
    if settings.get("cbz_path"):
        argv += ["--cbz-path", settings["cbz_path"]]
    argv.append(url)
    return argv


def argv_to_settings(argv):
    #the inverse of settings_to_argv, for reading a schema 1 sidecar that saved the command itself
    #rather than what it was made of. flags that describe the machine rather than the comic - chrome,
    #headless, verbose - are deliberately dropped rather than pinned into a comic's settings.
    settings = {"url": None, "output": None, "cbz_path": None, "increment": None, "prefix": False,
                "javascript": False, "firefox": False, "waittime": 0, "cbz": True, "ended": False}
    valued = {"--increment": "increment", "-i": "increment", "--output": "output", "-o": "output",
              "--cbz-path": "cbz_path", "--waittime": "waittime", "-w": "waittime"}
    flagged = {"--prefix": "prefix", "-p": "prefix", "--enable_javascript": "javascript",
               "-ej": "javascript", "--firefox": "firefox", "-f": "firefox"}
    at = 0
    argv = list(argv or [])
    while at < len(argv):
        token = argv[at]
        if token in valued and at + 1 < len(argv):
            settings[valued[token]] = argv[at + 1]
            at += 2
            continue
        if token in flagged:
            settings[flagged[token]] = True
        elif token == "--no-cbz":
            settings["cbz"] = False
        elif not token.startswith('-'):
            #the only bare word in a mirror_base command is the url it starts from
            settings["url"] = token
        at += 1
    try:
        settings["increment"] = int(settings["increment"])
    except (TypeError, ValueError):
        settings["increment"] = None
    try:
        settings["waittime"] = int(settings["waittime"])
    except (TypeError, ValueError):
        settings["waittime"] = 0
    return settings


def resume_argv(comic):
    settings = comic.metadata.get("settings")
    if settings:
        argv = settings_to_argv(settings)
    else:
        #schema 1 kept the command itself rather than what it was made of. read it so an un-migrated
        #comic still runs, and it gets rewritten in the current shape the next time it is scraped
        argv = comic.metadata.get("resume_argv")
        if argv:
            argv = list(argv)
        else:
            command = comic.metadata.get("resume_command_line")
            if not command:
                return None
            argv = shlex.split(command)
            #drop the leading "python mirror_base.py"
            while argv and (argv[0].startswith('python') or argv[0].endswith('.py')):
                argv.pop(0)
    if not argv:
        return None

    #the metadata file's own location is what says where this comic lives, so an --output left over from
    #an earlier arrangement of the library is corrected rather than believed. trusting it would scrape the
    #comic into a fresh folder somewhere else and quietly leave the real one behind.
    for flag in ("--output", "-o"):
        if flag in argv:
            at = argv.index(flag) + 1
            if at < len(argv) and argv[at] != comic.name:
                comic.moved_from = argv[at]
                argv[at] = comic.name
            break
    return argv


def still_running(runnable, every, stop):
    #a comic with hundreds of pages to fetch can hold the log still for minutes, which looks exactly
    #like the whole run having wedged. this says what is in flight, for how long, and how far it has
    #got - counted from the folder, since the scraper's own output is not readable until it exits.
    while not stop.wait(every):
        busy = [c for c in runnable if c.started_at and c.code is None]
        if not busy:
            continue
        now = time.time()
        parts = []
        for comic in sorted(busy, key=lambda c: c.started_at):
            gained = folder_pages(comic.folder) - comic.before
            so_far = ", +{0} page(s)".format(gained) if gained > 0 else ""
            parts.append("{0} ({1:.0f}s{2})".format(comic.name, now - comic.started_at, so_far))
        say("  ...     still going: {0}".format("; ".join(parts)))


def page_count(comic):
    #read the count back from the metadata the run just wrote, falling back to counting the folder
    try:
        with open(os.path.join(comic.folder, metadata_file), 'r', encoding='utf-8') as f:
            fresh = json.load(f)
            counted = (fresh.get("state") or {}).get("page_count", fresh.get("page_count"))
            if counted is not None:
                return counted
    except (ValueError, OSError):
        pass
    return folder_pages(comic.folder)


def kill_tree(process):
    #the browser is a child of mirror_base, so killing only the python process leaves chromedriver behind
    try:
        if os.name == 'nt':
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


def run_comic(comic, args):
    #each comic runs in its own process: mirror_base caches the xpaths it discovers in module globals, so
    #reusing one process would try the previous comic's paths, and a crash would take the whole run with it
    command = [sys.executable, args.script] + comic.argv
    started = time.time()
    comic.started_at = started
    say("  start   {0}".format(comic.name))
    #a new process group is what makes it possible to take the browser down with the script on a timeout
    grouping = {}
    if os.name == 'nt':
        grouping["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        grouping["start_new_session"] = True

    try:
        process = subprocess.Popen(command, cwd=args.root, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace', **grouping)
    except OSError as error:
        comic.code, comic.output = 5, "could not start {0}: {1}".format(args.script, error)
        comic.elapsed = time.time() - started
        return comic

    try:
        comic.output = process.communicate(timeout=args.timeout)[0] or ""
        comic.code = process.returncode
    except subprocess.TimeoutExpired:
        kill_tree(process)
        comic.output = "timed out after {0}s".format(args.timeout)
        comic.code = 124

    comic.elapsed = time.time() - started
    counted = page_count(comic)
    if counted is not None:
        comic.after = counted
    return comic


def describe(comic):
    if comic.skipped:
        return "skipped ({0})".format(comic.skipped)
    if comic.code == 124:
        return "TIMED OUT after {0:.0f}s".format(comic.elapsed)
    if comic.ok:
        return "up to date" if not comic.gained else "+{0} page{1}".format(
            comic.gained, "" if comic.gained == 1 else "s")
    return "FAILED exit {0} ({1})".format(comic.code, exit_reasons.get(comic.code, "unknown"))


def take_lock(root):
    #stops a manual run from colliding with a scheduled one that is still going
    path = os.path.join(root, lock_file)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                pid = int(f.read().strip())
            alive = True
            if os.name != 'nt':
                try:
                    os.kill(pid, 0)
                except OSError:
                    alive = False
            if alive:
                return None, "another update is already running (pid {0})".format(pid)
        except (ValueError, OSError):
            pass
        os.remove(path) #stale
    with open(path, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    return path, None


def setup():
    params = argparse.ArgumentParser(
        description="Updates every comic in a library folder by resuming it from its mirror_metadata.json.")
    params.add_argument("root", nargs='?', default=".",
                        help="Library folder holding one directory per comic. Defaults to the working directory.")
    params.add_argument("-j", "--jobs", type=int, default=1,
                        help="How many comics to update at once. Each one runs its own browser, so raise this only as far as memory allows. Defaults to 1.")
    params.add_argument("-t", "--timeout", type=int, default=1800,
                        help="Seconds any one comic may run before it is killed. Defaults to 1800.")
    params.add_argument("-o", "--only", action='append', default=None,
                        help="Update only the named comic folder. May be repeated, and takes wildcards: \"Group/*\" is every comic under Group, however deep.")
    params.add_argument("-n", "--dry-run", action='store_true', default=False,
                        help="List what would run, and the command each comic would use, without running anything.")
    params.add_argument("--script", default=None,
                        help="Path to mirror_base.py. Defaults to the copy beside this script.")
    params.add_argument("--max-depth", type=int, default=5,
                        help="How many folders deep to look for comics. Lets a library group comics by author or site. Defaults to 5.")
    params.add_argument("--schedule", default=None, metavar="HH:MM",
                        help="Stay running and start an update at this local time every day. Without it the update runs once and exits.")
    params.add_argument("--progress", type=int, default=60, metavar="SECONDS",
                        help="While a run is going, say every so often which comics are still going "
                             "and how far they have got. Defaults to 60 seconds; 0 turns it off.")
    params.add_argument("--now", action='store_true', default=False,
                        help="Update once straight away, then settle into --schedule. Without --schedule "
                             "this is what happens anyway. Useful for a container that should not sit "
                             "idle until the small hours the first time it starts.")
    args = params.parse_args()

    args.root = os.path.abspath(args.root)
    if args.script is None:
        args.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_base.py")
    return args


def report_skipped(comics):
    #ended comics are the bulk of a settled library and saying so a hundred times buries the one comic
    #that was skipped because something is actually wrong with it
    ended = [c for c in comics if c.skipped == ended_reason]
    problems = [c for c in comics if c.skipped and c.skipped != ended_reason]
    if ended:
        print("  {0} comic(s) left alone as ended.".format(len(ended)))
    for comic in problems:
        print("  {0:<40} SKIPPED: {1}".format(comic.name, comic.skipped))


def run_once(args):
    comics = find_comics(args.root, args.max_depth)
    if args.only:
        #match either the full path within the library or just the folder name, so a nested comic can be
        #named either way. wildcards work too, and * crosses folders, so Group/* takes every comic under Group
        wanted = [w.replace(chr(92), '/').strip('/') for w in args.only]

        def matches(comic, pattern):
            return any(fnmatch.fnmatch(name, pattern) for name in (comic.name, os.path.basename(comic.folder)))

        missing = [w for w in wanted if not any(matches(c, w) for c in comics)]
        comics = [c for c in comics if any(matches(c, w) for w in wanted)]
        for name in sorted(missing):
            print("WARNING: no comic named {0} in {1}.".format(name, args.root))
    if not comics:
        print("No comics with a {0} found in {1}.".format(metadata_file, args.root))
        return 0

    #a comic marked as ended in its metadata is finished for good, so there is nothing to check
    for comic in comics:
        if comic.skipped:
            continue
        if (comic.metadata.get("settings") or {}).get("ended", comic.metadata.get("ended")):
            comic.skipped = ended_reason
            continue
        comic.argv = resume_argv(comic)
        if not comic.argv:
            comic.skipped = "no resume command in metadata"

    runnable = [c for c in comics if not c.skipped]
    for comic in runnable:
        if comic.moved_from:
            print("NOTE: {0} still had --output {1} from an earlier layout; using its own folder.".format(
                comic.name, comic.moved_from))

    if args.dry_run:
        print("Would update {0} of {1} comic(s) in {2}:".format(len(runnable), len(comics), args.root))
        for comic in runnable:
            rendered = subprocess.list2cmdline(comic.argv) if os.name == 'nt' else shlex.join(comic.argv)
            print("  {0:<40} {1}".format(comic.name, rendered))
        report_skipped(comics)
        return 0

    lock, held_by = take_lock(args.root)
    if lock is None:
        print("ERROR: {0}".format(held_by))
        return 2

    started = time.time()
    #a daemon so a ctrl-c or a docker stop is never held up waiting for the next tick
    stop_watching = threading.Event()
    watcher = None
    if args.progress > 0:
        watcher = threading.Thread(target=still_running,
                                   args=(runnable, args.progress, stop_watching), daemon=True)
        watcher.start()
    try:
        print("Updating {0} comic(s) in {1}.".format(len(runnable), args.root))
        done = 0
        if args.jobs > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                #reported as each one finishes rather than in the order they were started. mapping in
                #order means one slow comic holds back the lines for every comic that overtook it, which
                #reads as though nothing else is running at all.
                waiting = [pool.submit(run_comic, comic, args) for comic in runnable]
                for future in as_completed(waiting):
                    comic = future.result()
                    done += 1
                    say("[{0}/{1}] {2:<40} {3} ({4:.0f}s)".format(
                        done, len(runnable), comic.name, describe(comic), comic.elapsed))
        else:
            for comic in runnable:
                done += 1
                run_comic(comic, args)
                say("[{0}/{1}] {2:<40} {3} ({4:.0f}s)".format(
                    done, len(runnable), comic.name, describe(comic), comic.elapsed))
    finally:
        stop_watching.set()
        try:
            os.remove(lock)
        except OSError:
            pass

    gained = [c for c in runnable if c.ok and c.gained]
    failed = [c for c in runnable if not c.ok]
    skipped = [c for c in comics if c.skipped]

    print()
    print("Finished in {0:.0f}s: {1} updated, {2} already current, {3} failed, {4} skipped.".format(
        time.time() - started, len(gained), len(runnable) - len(gained) - len(failed), len(failed), len(skipped)))
    for comic in gained:
        print("  {0:<40} +{1} page(s), now {2}".format(comic.name, comic.gained, comic.after))
    #named here too, since a comic that never ran is easy to miss among the ones that did
    for comic in skipped:
        if comic.skipped != ended_reason:
            print("  {0:<40} SKIPPED: {1}".format(comic.name, comic.skipped))
    if failed:
        print()
        print("Failures:")
        for comic in failed:
            print("  {0:<40} {1}".format(comic.name, describe(comic)))
            for line in [l for l in comic.output.splitlines() if l.strip()][-4:]:
                print("      {0}".format(line))

    #a non-zero result is what makes a scheduled run show up as failed, which is the point of the summary
    return 1 if failed else 0


def parse_schedule(text):
    hour, _, minute = text.partition(':')
    hour, minute = int(hour), int(minute)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(text)
    return hour, minute


def next_run(hour, minute):
    #worked out fresh before every sleep, so the daily time stays put across a clock change
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def local_zone():
    #what the machine believes its timezone is. in a container that is UTC unless TZ was passed in, which
    #is worth saying out loud: the schedule would otherwise quietly run hours away from when it was meant to
    return datetime.now().astimezone().tzname() or time.tzname[0]


def take_trigger(root):
    #returns the comics a trigger file asks for (an empty list meaning all of them), or None when there is
    #no trigger. the file is removed first, so a run that fails is not started again every half minute
    for name in trigger_files:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                wanted = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            os.remove(path)
        except (OSError, UnicodeDecodeError) as error:
            #left in place it would fire on every poll, so it is reported once and then ignored until replaced
            key = (path, os.path.getmtime(path) if os.path.exists(path) else None)
            if key in ignored_triggers:
                continue
            ignored_triggers.add(key)
            print("WARNING: could not read and remove {0}, so it is being ignored: {1}".format(path, error),
                  flush=True)
            continue
        return [w.replace('\\', '/').strip('/') for w in wanted]
    return None


ignored_triggers = set()


def wait_until(target, root):
    #sleeps towards the scheduled time in short steps, returning early with the comics a trigger file names
    while True:
        left = (target - datetime.now()).total_seconds()
        if left <= 0:
            return None
        time.sleep(min(left, trigger_poll))
        wanted = take_trigger(root)
        if wanted is not None:
            return wanted


def main():
    args = setup()
    if not os.path.isdir(args.root):
        print("ERROR: {0} is not a folder.".format(args.root))
        return 2
    if not os.path.exists(args.script):
        print("ERROR: could not find {0}.".format(args.script))
        return 2
    if not args.schedule:
        return run_once(args)

    try:
        hour, minute = parse_schedule(args.schedule)
    except ValueError:
        print("ERROR: --schedule wants a 24 hour time like 03:30, not {0}.".format(args.schedule))
        return 2

    #python gets no default signal handling as pid 1, so without this a docker stop would sit through its
    #whole kill timeout instead of shutting down and releasing the lock
    signal.signal(signal.SIGTERM, lambda *ignored: sys.exit(0))
    zone = local_zone()
    if not os.environ.get("TZ"):
        print("WARNING: TZ is not set, so this container is running on {0}. Set TZ to your own timezone "
              "or the update will run at the wrong hour.".format(zone))
    print("Updating every day at {0:02d}:{1:02d} {2}.".format(hour, minute, zone), flush=True)
    print("To update sooner, put a file named {0} in {1}; list comic folders in it, one per line, to update "
          "only those.".format(trigger_files[0], args.root), flush=True)
    if args.now:
        #a fresh container would otherwise do nothing at all until the first scheduled hour came round,
        #which makes it hard to tell a working setup from a broken one
        print("Running once now before waiting for the schedule.", flush=True)
        run_once(args)
    while True:
        target = next_run(hour, minute)
        wait = (target - datetime.now()).total_seconds()
        #the clock is printed rather than just the gap, so a wrong timezone is obvious at a glance
        print("It is now {0} {2}; next update at {1} ({3:.1f} hours away).".format(
            datetime.now().strftime("%Y-%m-%d %H:%M"), target.strftime("%Y-%m-%d %H:%M"),
            zone, wait / 3600), flush=True)
        wanted = wait_until(target, args.root)
        if wanted is None:
            run_once(args)
            continue
        #a triggered run is limited to the comics the file names, or everything when it names none
        triggered = copy.copy(args)
        if wanted:
            triggered.only = wanted
        print("Found an update-now file; updating {0} now.".format(", ".join(wanted) if wanted else "everything"),
              flush=True)
        run_once(triggered)


if __name__ == "__main__":
    sys.exit(main())
