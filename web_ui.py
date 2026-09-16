#a small web page for update_comics: watch what a run is doing, start updates, add new comics, stop things.
#standard library only, so the container needs nothing new. started by update_comics.py --web PORT. #V 1.0

import ast
import base64
import collections
import copy
import hmac
import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

#the settings a person may change from the page, and what each one has to be. output is left out on
#purpose: a comic's folder is what says where it lives, and update_comics ignores a stored output anyway
editable = {
    "url": "url",
    "increment": "count",
    "cbz_path": "text",
    "prefix": "flag",
    "javascript": "flag",
    "firefox": "flag",
    "waittime": "count",
    "cbz": "flag",
    "direction_check": "flag",
    "ended": "flag",
}
max_edits = 50
#the file mirror_base reads its element paths from, kept in the library so the container can write to it
element_file = "element_paths.json"
kinds = ("image", "next")

page_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_ui.html")


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
                #a comic being kept in chapters has no use for the single archive, so it is never built:
                #the chapter archives are written from the folder once the pages are there
                "cbz": options["cbz"] and not listing,
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
            #a new comic can be thousands of pages, so only priming keeps the usual limit. a stalled page
            #still ends on its own through mirror_base's page timeout, and anything else can be stopped here
            if not options["prime"]:
                chosen.timeout = 0
            job.comics = comics
            code = uc.run_batch(comics, comics, chosen, "Priming" if options["prime"] else "Scraping")
            for comic in comics:
                if not comic.ok or not listings.get(comic.name):
                    continue
                #a primed comic has one page and no chapters to find yet, so the archive page is written
                #down and the chapters are worked out by the update that fetches the rest
                remember_listing(comic, listings[comic.name])
                if not options["prime"]:
                    split_into_chapters(comic, listings[comic.name], chosen, self.uc)
            return code

        verb = "Prime" if options["prime"] else "Scrape"
        label = "{0} {1}".format(verb, comics[0].name if len(comics) == 1 else "{0} new comics".format(len(comics)))
        return self.submit(Job("add", label, work))


def remember_listing(comic, listing):
    #so a later run knows where this comic's chapters are listed, whoever starts it
    path = os.path.join(comic.folder, "mirror_metadata.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (OSError, ValueError):
        return
    block = metadata.setdefault("chapters", {})
    if block.get("source_url") == listing:
        return
    block["source"] = "archive"
    block["source_url"] = listing
    block.setdefault("list", [])
    write_json(path, metadata)
    print("  {0}: chapters will be read from {1}".format(comic.name, listing), flush=True)


def split_into_chapters(comic, listing, args, uc):
    #a new comic that was given a chapter list: line up what was just saved, read the list, and write one
    #archive per chapter. every step says what it did, and none of them touches the pages themselves.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    if not os.path.exists(script):
        return
    #--replace because a comic kept in chapters keeps no single archive: the one the scrape just built
    #is given up as soon as every page is checked to be in a chapter
    steps = [["align"], ["chapters", "--archive", listing, "--save"], ["pack", "--replace"]]
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


def comic_view(comic, uc, live):
    if comic.stopped:
        state = "stopped"
    elif comic.started_at is None:
        state = "waiting"
    elif comic.code is None:
        state = "running"
    else:
        state = "ok" if comic.ok else "failed"
    if state == "running" and live:
        gained = max(uc.folder_pages(comic.folder) - comic.before, 0)
        elapsed = time.time() - comic.started_at
    else:
        gained, elapsed = comic.gained, comic.elapsed
    view = {"name": comic.name, "state": state, "gained": gained, "elapsed": round(elapsed)}
    if state in ("ok", "failed", "stopped"):
        view["detail"] = uc.describe(comic)
    if state == "running":
        view["last_line"] = comic.last_line
    if state == "failed":
        view["tail"] = [line for line in comic.output.splitlines() if line.strip()][-4:]
    return view


def job_view(job, uc, live=False):
    view = {"id": job.id, "kind": job.kind, "label": job.label, "created": job.created,
            "started": job.started, "finished": job.finished, "error": job.error,
            "stopping": job.cancel.is_set()}
    if job.kind == "check":
        view["check"] = job.check
        return view
    if job.started is None:
        return view
    comics = [comic_view(comic, uc, live) for comic in job.comics]
    counts = collections.Counter(c["state"] for c in comics)
    view["counts"] = dict(counts)
    view["gained"] = sum(c["gained"] for c in comics)
    if live:
        #waiting and running first, since that is what someone watching wants to see
        order = {"running": 0, "failed": 1, "stopped": 2, "ok": 3, "waiting": 4}
        view["comics"] = sorted(comics, key=lambda c: order[c["state"]])
    else:
        #a finished update of a whole library is mostly comics with nothing new, so only what moved is kept
        view["comics"] = [c for c in comics if c["state"] != "ok" or c["gained"]]
    return view


def library_view(args, uc):
    rows = []
    for comic in uc.find_comics(args.root, args.max_depth):
        meta = comic.metadata
        settings = meta.get("settings") or {}
        runs = (meta.get("history") or {}).get("runs") or meta.get("runs") or []
        last = runs[-1] if runs else {}
        ended = bool(settings.get("ended", meta.get("ended", False)))
        rows.append({
            "name": comic.name,
            "pages": comic.before,
            "ended": ended,
            "url": settings.get("url") or meta.get("resume_url"),
            "updated": meta.get("updated") or last.get("updated"),
            "exit_code": last.get("exit_code"),
            "stop_reason": last.get("stop_reason"),
            "problem": comic.skipped,
        })
    return rows


def shipped_paths(script):
    #the lists as mirror_base has them, with the comment beside each one, which is usually the name of the
    #comic it was added for. the values are read as python rather than scanned for, because an xpath is
    #full of brackets and quotes of its own; the comments, which python throws away, are matched after.
    lists = {"image": [], "next": []}
    names = {"element_names": "image", "next_ele_names": "next"}
    try:
        with open(script, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return lists
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        for target in node.targets:
            kind = names.get(getattr(target, "id", None))
            if not kind:
                continue
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    lists[kind].append({"xpath": item.value, "note": ""})
    notes = {}
    for line in source.splitlines():
        found = re.match(r"^\s*'(.*)'\s*,?\s*#\s*(.+?)\s*$", line)
        if found:
            notes[found.group(1)] = found.group(2)
    for entries in lists.values():
        for entry in entries:
            entry["note"] = notes.get(entry["xpath"], "")
    return lists


def element_paths_path(args, uc):
    #the config folder is where it belongs now. a file left in the library from an earlier version is still
    #read, and saving writes the config copy, which is the one mirror_base prefers from then on.
    path = os.path.join(uc.config_folder(), element_file)
    if os.path.exists(path):
        return path
    older = os.path.join(args.root, element_file)
    return older if os.path.exists(older) else path


def element_settings(args, uc):
    #what the page shows: everything mirror_base would try, in the order it would try it, marked with where
    #it came from. the built-in list is the base, and the saved file says what was reordered, added or
    #turned off - so a path added to the script later still turns up here.
    path = element_paths_path(args, uc)
    saved = {}
    problem = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                saved = json.load(f)
        except (OSError, ValueError) as error:
            problem = "could not read {0}: {1}".format(path, error)
    shipped = shipped_paths(args.script)
    lists = {}
    for kind in kinds:
        from_script = {entry["xpath"]: entry.get("note", "") for entry in shipped[kind]}
        seen, ordered = set(), []
        for entry in saved.get(kind) or []:
            xpath = (entry or {}).get("xpath")
            if not xpath or xpath in seen:
                continue
            seen.add(xpath)
            ordered.append({"xpath": xpath, "note": entry.get("note") or from_script.get(xpath, ""),
                            "enabled": entry.get("enabled", True), "shipped": xpath in from_script})
        #anything the file never mentioned is still live, and mirror_base puts it after what the file lists
        ordered += [{"xpath": entry["xpath"], "note": entry.get("note", ""), "enabled": True, "shipped": True}
                    for entry in shipped[kind] if entry["xpath"] not in seen]
        lists[kind] = ordered
    return {"path": path, "saved": bool(saved), "problem": problem,
            "image": lists["image"], "next": lists["next"]}


def save_elements(args, uc, given):
    cleaned, problems = {}, []
    for kind in kinds:
        entries, seen = [], set()
        for entry in given.get(kind) or []:
            xpath = str((entry or {}).get("xpath") or "").strip()
            if not xpath:
                continue
            if not xpath.startswith(("/", "(", ".")):
                problems.append("{0}: {1} does not look like an xpath".format(kind, xpath[:60]))
                continue
            if xpath in seen:
                problems.append("{0}: {1} is listed twice".format(kind, xpath[:60]))
                continue
            seen.add(xpath)
            entries.append({"xpath": xpath, "note": str(entry.get("note") or "").strip(),
                            "enabled": entry.get("enabled", True) is not False})
        if not [entry for entry in entries if entry["enabled"]]:
            problems.append("{0}: at least one path has to be left on".format(kind))
        cleaned[kind] = entries
    if problems:
        return 400, {"error": "; ".join(problems)}

    path = os.path.join(uc.config_folder(), element_file)
    body = {"note": "Element paths for mirror_base.py. The order here is the order they are tried; "
                    "anything not listed is added after them.",
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    body.update(cleaned)
    try:
        write_json(path, body)
    except OSError as error:
        return 500, {"error": "could not write {0}: {1}".format(path, error)}
    print("Saved {0}: {1} image path(s), {2} next path(s)".format(
        path, len([e for e in cleaned["image"] if e["enabled"]]),
        len([e for e in cleaned["next"] if e["enabled"]])), flush=True)
    return 200, {"saved": True, "path": path}


def find_comic(args, uc, name):
    for comic in uc.find_comics(args.root, args.max_depth):
        if comic.name == name:
            return comic
    return None


def is_running(runner, name):
    job = runner.current
    return bool(job) and any(c.name == name and c.started_at and c.code is None for c in job.comics)


def read_metadata(path):
    with open(path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if metadata.get("schema", 1) < 2:
        #an old sidecar is brought up to date first, so the edit lands in the one place a run reads it
        import adopt_comic
        metadata = adopt_comic.migrate_metadata(metadata) or metadata
    return metadata


def comic_detail(args, uc, runner, name):
    comic = find_comic(args, uc, name)
    if comic is None:
        return None, "no comic named {0}".format(name)
    path = os.path.join(comic.folder, uc.metadata_file)
    try:
        metadata = read_metadata(path)
    except (OSError, ValueError) as error:
        return None, "could not read {0}: {1}".format(path, error)
    history = metadata.get("history") or {}
    runs = history.get("runs") or []
    return {
        "name": comic.name,
        "updated": metadata.get("updated"),
        "settings": metadata.get("settings") or {},
        "state": metadata.get("state") or {},
        "first_page_url": history.get("first_page_url"),
        "runs": [{key: run.get(key) for key in ("started", "start_url", "start_page_number", "last_url",
                                                "last_page_number", "pages_saved", "stop_reason", "exit_code")}
                 for run in runs[-8:]][::-1],
        "edits": (history.get("edits") or [])[-8:][::-1],
        "pages_in_folder": uc.folder_pages(comic.folder),
        "running": is_running(runner, comic.name),
    }, None


def clean_settings(given):
    #checks each value the page sent, so a typo turns into a message rather than a comic that will not run
    cleaned, problems = {}, []
    for key, kind in editable.items():
        if key not in given:
            continue
        value = given[key]
        if kind == "flag":
            cleaned[key] = bool(value)
        elif kind == "count":
            try:
                number = int(str(value).strip() or 0)
                if number < 0:
                    raise ValueError
                cleaned[key] = number
            except ValueError:
                problems.append("{0} must be a whole number, 0 or more".format(key))
        elif kind == "url":
            text = str(value or "").strip()
            if not re.match(r"^https?://\S+$", text):
                problems.append("the start page must be a full http(s) address")
            else:
                cleaned[key] = text
        else:
            text = str(value or "").strip()
            cleaned[key] = text or None
    return cleaned, problems


def save_settings(args, uc, runner, name, given, expected_updated):
    comic = find_comic(args, uc, name)
    if comic is None:
        return 404, {"error": "no comic named {0}".format(name)}
    #a running scrape rewrites this file after every page, and would quietly put back whatever it started with
    if is_running(runner, comic.name):
        return 409, {"error": "{0} is being scraped right now; stop it or wait for it to finish".format(name)}
    cleaned, problems = clean_settings(given)
    if problems:
        return 400, {"error": "; ".join(problems)}

    path = os.path.join(comic.folder, uc.metadata_file)
    try:
        metadata = read_metadata(path)
    except (OSError, ValueError) as error:
        return 500, {"error": "could not read {0}: {1}".format(path, error)}
    if expected_updated and metadata.get("updated") != expected_updated:
        return 409, {"error": "the metadata changed since it was opened (a run may have written it). "
                              "Reopen it and make the change again."}

    settings = dict(metadata.get("settings") or {})
    changed = {key: [settings.get(key), value] for key, value in cleaned.items() if settings.get(key) != value}
    if not changed:
        return 200, {"saved": False, "message": "nothing changed"}
    settings.update(cleaned)
    metadata["settings"] = settings
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata["updated"] = stamp
    history = metadata.setdefault("history", {})
    history["edits"] = (history.get("edits") or [])[-(max_edits - 1):] + [{"at": stamp, "changed": changed}]

    #written beside the real file and swapped in, so a crash part way never leaves half a metadata file
    spare = path + ".editing"
    with open(spare, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")
    os.replace(spare, path)
    print("Edited {0}: {1}".format(comic.name, ", ".join(
        "{0} {1} -> {2}".format(key, json.dumps(old), json.dumps(new)) for key, (old, new) in changed.items())),
        flush=True)
    return 200, {"saved": True, "changed": changed, "updated": stamp}


def write_json(path, body):
    #written beside the real file and swapped in, so a crash part way never leaves half a file
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    spare = path + ".editing"
    with open(spare, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
        f.write("\n")
    os.replace(spare, path)


def config_view(args, uc):
    saved = uc.load_config(quiet=True)
    return {"path": uc.config_path(), "saved": os.path.exists(uc.config_path()),
            "settings": saved, "defaults": uc.config_defaults,
            "restart_needed": ["schedule"], "root": args.root,
            "from_command_line": sorted(getattr(args, "from_command_line", []))}


def save_config(args, uc, given):
    #only the settings that are known, so the file cannot fill up with things nothing reads
    saved, problems = {}, []
    for key, fallback in uc.config_defaults.items():
        if key not in given:
            continue
        value = given[key]
        if key == "add_defaults" and isinstance(value, dict):
            saved[key] = {name: value.get(name, default) for name, default in fallback.items()}
        elif key in ("pages_folder", "cbz_folder"):
            folder = clean_folder(str(value or ""))
            if folder is None:
                problems.append("{0} has to be a folder inside the library".format(key))
            else:
                saved[key] = folder
        elif key == "schedule":
            text = str(value or "").strip()
            if text:
                try:
                    uc.parse_schedule(text)
                except ValueError:
                    problems.append("the schedule wants a 24 hour time like 03:30")
            saved[key] = text or None
        else:
            try:
                number = int(value)
                if number < 0:
                    raise ValueError
                saved[key] = number
            except (TypeError, ValueError):
                problems.append("{0} has to be a whole number, 0 or more".format(key))
    if saved.get("jobs") == 0:
        problems.append("jobs has to be at least 1")
    if problems:
        return 400, {"error": "; ".join(problems)}
    try:
        write_json(uc.config_path(), saved)
    except OSError as error:
        return 500, {"error": "could not write {0}: {1}".format(uc.config_path(), error)}
    print("Saved {0}".format(uc.config_path()), flush=True)
    return 200, {"saved": True, "path": uc.config_path(), "settings": uc.load_config(quiet=True)}


def default_cbz(folder):
    #readers dislike archives loose in a folder, so a comic with no folder of its own is given one. a comic
    #already inside a group folder has one, and its archive sits beside its siblings.
    parts = folder.split("/")
    return "{0}/{1}.cbz".format(folder, parts[-1]) if len(parts) == 1 else folder + ".cbz"


def under_root(root, folder):
    #the table holds paths inside the pages or archive folder, but typing the whole thing has to work too
    folder = folder.strip("/")
    first = folder.split("/")[0].lower()
    if root and first == root.strip("/").lower():
        return folder
    return "{0}/{1}".format(root.strip("/"), folder) if root else folder


def clean_folder(text):
    #a folder inside the library, never outside it
    folder = text.strip().strip('"').replace(chr(92), "/").strip("/")
    parts = [part for part in folder.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or re.match(r"^[A-Za-z]:", folder):
        return None
    return "/".join(parts)


def parse_entries(rows, args):
    #one comic per row: where its pages go, where its archive goes, and the page to start from. the two
    #folders are given relative to the library's pages and archive folders, since that is all that differs
    #between one comic and the next.
    entries, problems = [], []
    for number, row in enumerate(rows or [], 1):
        if isinstance(row, str):
            row = {"folder": row}
        url = str((row or {}).get("url") or "").strip().strip('"')
        folder = clean_folder(str(row.get("folder") or ""))
        archive = str(row.get("cbz") or "").strip().strip('"')
        listing = str(row.get("chapters") or "").strip().strip('"')
        if not url and not folder and not archive and not listing:
            continue
        if listing and not re.match(r"^https?://\S+$", listing):
            problems.append("row {0}: the chapter list has to be an http(s) address".format(number))
            continue
        if not re.match(r"^https?://\S+$", url):
            problems.append("row {0}: needs one http(s) address".format(number))
            continue
        if folder is None:
            problems.append("row {0}: needs a folder, like MyComic or Series/MyComic".format(number))
            continue
        pages_at = under_root(args.pages_folder, folder)
        archive = clean_folder(archive) if archive else None
        if row.get("cbz") and archive is None:
            problems.append("row {0}: the archive path is not a path inside the library".format(number))
            continue
        archive_at = under_root(args.cbz_folder, archive or default_cbz(folder))
        if not archive_at.lower().endswith(".cbz"):
            archive_at += ".cbz"
        if os.path.exists(os.path.join(args.root, *pages_at.split("/"), "mirror_metadata.json")):
            problems.append("row {0}: {1} is already in the library; update it instead".format(number, pages_at))
            continue
        entries.append((pages_at, archive_at, url, listing))
    seen = set()
    for pages_at, _, _, _ in entries:
        if pages_at in seen:
            problems.append("{0} is listed twice".format(pages_at))
        seen.add(pages_at)
    return entries, problems


def make_handler(runner, args, uc, tee):
    password = os.environ.get("MIRROR_WEB_PASSWORD") or ""

    class Handler(BaseHTTPRequestHandler):
        server_version = "update_comics"

        def log_message(self, *ignored):
            pass

        def allowed(self):
            if not password:
                return True
            given = self.headers.get("Authorization", "")
            if given.startswith("Basic "):
                try:
                    _, _, secret = base64.b64decode(given[6:]).decode("utf-8").partition(":")
                    if hmac.compare_digest(secret, password):
                        return True
                except (ValueError, UnicodeDecodeError):
                    pass
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="update_comics"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def reply(self, body, status=200, kind="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return
            where = urlsplit(self.path)
            if where.path == "/":
                #read on every request, so editing the page needs no restart
                try:
                    with open(page_file, "rb") as f:
                        self.reply(f.read(), kind="text/html; charset=utf-8")
                except OSError as error:
                    self.reply("web_ui.html is missing: {0}".format(error).encode(), 500, "text/plain")
            elif where.path == "/api/state":
                since = int((parse_qs(where.query).get("since") or ["0"])[0] or 0)
                lines, seq = tee.since(since)
                with runner.changed:
                    current, waiting, history = runner.current, list(runner.waiting), list(runner.history)
                self.reply({
                    "now": time.time(),
                    "root": args.root,
                    "jobs_at_once": args.jobs,
                    "next_run": runner.next_run.timestamp() if runner.next_run else None,
                    "current": job_view(current, uc, live=True) if current else None,
                    "waiting": [job_view(job, uc) for job in waiting],
                    "history": [job_view(job, uc) for job in history],
                    "log": [{"seq": s, "at": at, "text": text} for s, at, text in lines],
                    "seq": seq,
                })
            elif where.path == "/api/config":
                self.reply(config_view(args, uc))
            elif where.path == "/api/elements":
                self.reply(element_settings(args, uc))
            elif where.path == "/api/comics":
                self.reply(library_view(args, uc))
            elif where.path == "/api/comic":
                name = (parse_qs(where.query).get("name") or [""])[0]
                detail, problem = comic_detail(args, uc, runner, name)
                self.reply(detail if detail else {"error": problem}, 200 if detail else 404)
            else:
                self.reply({"error": "not found"}, 404)

        def do_POST(self):
            if not self.allowed():
                return
            #json only: a page on another site cannot send that without the browser asking first, which is
            #what keeps a stray link from starting scrapes
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self.reply({"error": "send json"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.reply({"error": "that was not json"}, 400)
                return
            path = urlsplit(self.path).path

            if path == "/api/update":
                names = [str(name) for name in body.get("names") or []]
                job = runner.submit_update(names, "Started from the web page")
                self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/add":
                entries, problems = parse_entries(body.get("rows") or body.get("entries") or [],
                                                  uc.with_config(args))
                #whatever the request did not say is taken from the settings file, so adding a comic
                #through the page and adding one any other way start from the same options
                fallback = uc.load_config().get("add_defaults", {})
                try:
                    options = {}
                    for key in ("prime", "prefix", "javascript", "cbz", "direction_check"):
                        options[key] = bool(body[key]) if key in body else bool(fallback.get(key))
                    for key, floor in (("increment", 1), ("waittime", 0)):
                        given = body.get(key, fallback.get(key, floor))
                        options[key] = int(given if given not in ("", None) else floor)
                except (TypeError, ValueError):
                    problems.append("the starting number and wait time must be whole numbers")
                if problems:
                    self.reply({"error": "; ".join(problems)}, 400)
                elif not entries:
                    self.reply({"error": "no comics given"}, 400)
                else:
                    job = runner.submit_add(entries, options)
                    self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/settings":
                name = str(body.get("name") or "")
                status, result = save_settings(args, uc, runner, name, body.get("settings") or {},
                                               body.get("updated"))
                if status == 200 and body.get("update_after"):
                    job = runner.submit_update([name], "Edited on the web page")
                    result["queued"] = job.label
                self.reply(result, status)
            elif path == "/api/config":
                status, result = save_config(args, uc, body.get("settings") or {})
                self.reply(result, status)
            elif path == "/api/elements":
                status, result = save_elements(args, uc, body)
                self.reply(result, status)
            elif path == "/api/check":
                url = str(body.get("url") or "").strip()
                if not re.match(r"^https?://\S+$", url):
                    self.reply({"error": "that is not a full http(s) address"}, 400)
                else:
                    job = runner.submit_check(url)
                    self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/stop":
                self.reply({"stopping": runner.stop()})
            elif path == "/api/drop":
                self.reply({"dropped": runner.drop(int(body.get("id") or 0))})
            else:
                self.reply({"error": "not found"}, 404)

    return Handler


def start(args, uc):
    tee = LogTee(sys.stdout)
    sys.stdout = tee
    runner = Runner(args, uc)
    server = ThreadingHTTPServer((args.web_host, args.web), make_handler(runner, args, uc, tee))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    shown = "localhost" if args.web_host in ("0.0.0.0", "", "::") else args.web_host
    print("Web page on http://{0}:{1}/{2}".format(
        shown, args.web, "" if os.environ.get("MIRROR_WEB_PASSWORD") else
        " (no password set; anyone who can reach this port can start scrapes)"), flush=True)
    return runner
