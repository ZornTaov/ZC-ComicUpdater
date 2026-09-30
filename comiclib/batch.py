#one update of a library: each comic run as its own mirror_base process, a few at once, none allowed to run
#forever, a chaptered comic's archives written again once it gains pages, and a summary of what moved.
import copy
import fnmatch
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from comiclib import exits
from comiclib.chapters.index import index_path
from comiclib.config import load_config
from comiclib.library import find_comics, page_count, resume_argv
from comiclib.metadata import METADATA_FILE as metadata_file
from comiclib.pages import count as folder_pages

#a comic marked this way is meant to be left alone for good, so it is counted rather than listed.
#anything skipped for any other reason is a problem, and gets named.
ended_reason = "marked as ended"
#print() writes its text and its newline separately, so two comics finishing at once could tear each
#other's lines in half. everything a worker prints goes through here instead: one line, one write.
print_lock = threading.Lock()
lock_file = ".update_comics.lock"
#the code a comic gets when it is stopped by hand rather than failing on its own
stopped_code = 130
#mirror_base's exit codes, so the summary can say what actually went wrong
exit_reasons = exits.REASONS


def say(line):
    with print_lock:
        sys.stdout.write(line + chr(10))
        sys.stdout.flush()


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


def own_group():
    #a new process group is what makes it possible to take the browser down with the script that started it
    if os.name == 'nt':
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def run_comic(comic, args):
    #each comic runs in its own process: mirror_base caches the xpaths it discovers in module globals, so
    #reusing one process would try the previous comic's paths, and a crash would take the whole run with it
    command = [sys.executable, args.script] + comic.argv
    started = time.time()
    cancel = getattr(args, "cancel", None)
    if cancel is not None and cancel.is_set():
        #stopped before its turn came, so it never starts at all
        comic.stopped, comic.code = True, stopped_code
        return comic
    comic.started_at = started
    say("  start   {0}".format(comic.name))
    grouping = own_group()

    try:
        #unbuffered, or python holds a piped child's output back in blocks and a live view sees nothing for minutes
        process = subprocess.Popen(command, cwd=args.root, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   env=dict(os.environ, PYTHONUNBUFFERED="1"), **grouping)
    except OSError as error:
        comic.code, comic.output = 5, "could not start {0}: {1}".format(args.script, error)
        comic.elapsed = time.time() - started
        return comic

    #read as it arrives rather than all at the end, so the last line can be shown while a long scrape runs
    comic.process = process
    said = []

    def listen():
        for line in process.stdout:
            said.append(line)
            if line.strip():
                comic.last_line = line.rstrip()

    listener = threading.Thread(target=listen, daemon=True)
    listener.start()
    try:
        process.wait(timeout=args.timeout or None)
        comic.code = stopped_code if comic.stopped else process.returncode
    except subprocess.TimeoutExpired:
        kill_tree(process)
        said.append("timed out after {0}s\n".format(args.timeout))
        comic.code = 124
    listener.join(timeout=15)
    comic.output = "".join(said)

    comic.elapsed = time.time() - started
    counted = page_count(comic)
    if counted is not None:
        comic.after = counted
    #only worth doing when the comic actually gained something, and only for a comic that is in chapters.
    #however the run ended, short of being stopped by hand: the pages a run saved before it timed out or
    #failed are whole and in the index, and left unpacked they would wait for a later run that both gains
    #pages and finishes - a comic that fails at its newest page every day would never have them packed
    known = comic.metadata.get("chapters") or {}
    if (comic.gained and not comic.stopped and getattr(args, "pack_chapters", True)
            and (known.get("list") or known.get("source_url") or known.get("every"))):
        try:
            pack_chapters(comic, args)
        except (OSError, subprocess.SubprocessError) as error:
            say("  {0:<40} chapters: could not be written ({1})".format(comic.name, error))
    return comic


def read_chapters(comic):
    #read fresh, because the step before this one may have just written them
    try:
        with open(os.path.join(comic.folder, metadata_file), 'r', encoding='utf-8') as f:
            return json.load(f).get("chapters")
    except (OSError, ValueError):
        return None


def pack_chapters(comic, args):
    #a comic split into chapters keeps no single archive, so the pages it just gained are not in any
    #archive until this runs. lining up first is what puts the new pages in the index in order.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    if not os.path.exists(script):
        return
    #lined up first, so the pages just saved are in the index; then the archive page is read again, since
    #a new chapter usually begins on one of those pages and could not have been placed before they existed
    known = comic.metadata.get("chapters") or {}
    #a comic cut by size that was never walked has nothing to line up: its filenames say which page is which
    walked = os.path.exists(index_path(comic.folder, args.root))
    steps = ["align"] if walked or not known.get("every") else []
    #reading the archive page again is how a new chapter is found; for a comic that has a page to read but
    #no chapters worked out yet - one that was primed with a chapter list - it is how the first ones arrive
    if known.get("source_url") and (getattr(args, "refresh_chapters", True) or not known.get("list")):
        steps.append("chapters")
    #a comic cut every so many pages needs its next part once the last one fills. that reads nothing from
    #the site, so it is done whether or not archive pages are being read again
    elif known.get("every"):
        steps.append("chapters")
    #a comic set to keep no archives still has its chapters worked out and its index kept - all of that
    #is knowledge about the comic. only the writing of archives waits for that switch to be turned on.
    if (comic.metadata.get("settings") or {}).get("cbz") is False:
        say("  {0:<40} chapters: worked out, but this comic keeps no archives (cbz is off)".format(comic.name))
    else:
        steps.append("pack")
    for what in steps:
        done = subprocess.run([sys.executable, script, what, comic.folder, "--root", args.root]
                              + (["--save"] if what == "chapters" else []),
                              capture_output=True, text=True, errors='replace',
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=args.timeout or None)
        if what == "pack" and not (read_chapters(comic) or {}).get("list"):
            say("  {0:<40} chapters: none could be worked out, so nothing was packed".format(comic.name))
            return
        if what == "chapters":
            #a refusal here is a decision to make by hand, not a failure: the pages are saved either way
            for line in (done.stdout or "").splitlines():
                if "more than before" in line or "WARNING:" in line or "because pages would move" in line:
                    say("  {0:<40} chapters: {1}".format(comic.name, line.strip()[:110]))
            continue
        if done.returncode != 0:
            say("  {0:<40} chapters: {1} said no ({2})".format(
                comic.name, what, (done.stdout or done.stderr).strip().splitlines()[-1][:80]
                if (done.stdout or done.stderr).strip() else "exit {0}".format(done.returncode)))
            return
    if "pack" not in steps:
        return
    wrote = [line for line in (done.stdout or "").splitlines() if line.strip().startswith("wrote ")]
    say("  {0:<40} chapters: {1}".format(comic.name, "{0} archive(s) written".format(len(wrote))
                                         if wrote else "already up to date"))


def pages_gained(comic):
    return "+{0} page{1}".format(comic.gained, "" if comic.gained == 1 else "s")


def went_wrong(comic):
    #how a run that did not finish cleanly ended
    if comic.code == 124:
        return "TIMED OUT after {0:.0f}s".format(comic.elapsed)
    if comic.stopped:
        return "stopped"
    return "FAILED exit {0} ({1})".format(comic.code, exit_reasons.get(comic.code, "unknown"))


def describe(comic):
    if comic.skipped:
        return "skipped ({0})".format(comic.skipped)
    if comic.ok:
        return "up to date" if not comic.gained else pages_gained(comic)
    #a run that ends badly has usually saved pages first: a long catch-up is exactly what runs into the
    #timeout, and every page it saved before then is whole and kept. leaving them out of the line made a
    #comic that gained two hundred pages read as though it had gained nothing
    return went_wrong(comic) + (", " + pages_gained(comic) if comic.gained else "")


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


def report_skipped(comics):
    #ended comics are the bulk of a settled library and saying so a hundred times buries the one comic
    #that was skipped because something is actually wrong with it
    ended = [c for c in comics if c.skipped == ended_reason]
    problems = [c for c in comics if c.skipped and c.skipped != ended_reason]
    if ended:
        print("  {0} comic(s) left alone as ended.".format(len(ended)))
    for comic in problems:
        print("  {0:<40} SKIPPED: {1}".format(comic.name, comic.skipped))


def select_comics(args):
    #the comics a run covers and, of those, the ones it will actually start
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
        return [], []

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
    return comics, runnable


def with_config(args):
    #re-read before each run, so editing the settings does not need a restart. only the values a run uses
    #are taken; the schedule is read once at startup because it is what the waiting loop is built around.
    saved = load_config(quiet=True)
    fresh = copy.copy(args)
    for key in ("jobs", "timeout", "progress", "max_depth", "pack_chapters", "refresh_chapters"):
        if key not in getattr(args, "from_command_line", ()):
            setattr(fresh, key, saved[key])
    fresh.pages_folder = saved["pages_folder"]
    fresh.cbz_folder = saved["cbz_folder"]
    return fresh


def run_once(args):
    comics, runnable = select_comics(args)
    if not comics:
        return 0
    if args.dry_run:
        print("Would update {0} of {1} comic(s) in {2}:".format(len(runnable), len(comics), args.root))
        for comic in runnable:
            rendered = subprocess.list2cmdline(comic.argv) if os.name == 'nt' else shlex.join(comic.argv)
            print("  {0:<40} {1}".format(comic.name, rendered))
        report_skipped(comics)
        return 0
    return run_batch(comics, runnable, args)


def run_batch(comics, runnable, args, doing="Updating"):
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
        print("{0} {1} comic(s) in {2}.".format(doing, len(runnable), args.root))
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

    #pages gained however the run ended, so a comic that timed out part way through a catch-up is counted
    #as updated as well as failed: both are true
    gained = [c for c in runnable if c.gained]
    current = [c for c in runnable if c.ok and not c.gained]
    stopped = [c for c in runnable if c.stopped]
    failed = [c for c in runnable if not c.ok and not c.stopped]
    skipped = [c for c in comics if c.skipped]

    print()
    print("Finished in {0:.0f}s: {1} updated, {2} already current, {3} failed, {4} skipped{5}.".format(
        time.time() - started, len(gained), len(current), len(failed), len(skipped),
        ", {0} stopped".format(len(stopped)) if stopped else ""))
    for comic in gained:
        print("  {0:<40} +{1} page(s), now {2}{3}".format(comic.name, comic.gained, comic.after,
                                                        "" if comic.ok else ", then " + went_wrong(comic)))
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
