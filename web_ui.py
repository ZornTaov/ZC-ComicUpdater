#a small web page for update_comics: watch what a run is doing, start updates, add new comics, stop things.
#standard library only, so the container needs nothing new. started by update_comics.py --web PORT. #V 1.0

import base64
import collections
import copy
import hmac
import itertools
import json
import os
import re
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
            chosen = copy.copy(self.args)
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

    def submit_add(self, entries, options):
        uc = self.uc
        comics = []
        for folder, url in entries:
            settings = {
                "url": url,
                "output": folder,
                "increment": options["increment"],
                "prefix": options["prefix"],
                "javascript": options["javascript"],
                "waittime": options["waittime"],
                "cbz": options["cbz"],
                "direction_check": options["direction_check"],
            }
            comic = uc.Comic(os.path.join(self.args.root, *folder.split("/")), {}, self.args.root)
            comic.argv = uc.settings_to_argv(settings)
            if options["prime"]:
                comic.argv.insert(0, "--prime")
            comics.append(comic)

        def work(job):
            chosen = copy.copy(self.args)
            chosen.cancel = job.cancel
            #a new comic can be thousands of pages, so only priming keeps the usual limit. a stalled page
            #still ends on its own through mirror_base's page timeout, and anything else can be stopped here
            if not options["prime"]:
                chosen.timeout = 0
            job.comics = comics
            return uc.run_batch(comics, comics, chosen, "Priming" if options["prime"] else "Scraping")

        verb = "Prime" if options["prime"] else "Scrape"
        label = "{0} {1}".format(verb, comics[0].name if len(comics) == 1 else "{0} new comics".format(len(comics)))
        return self.submit(Job("add", label, work))


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


def clean_folder(text):
    #a folder inside the library, never outside it
    folder = text.strip().strip('"').replace(chr(92), "/").strip("/")
    parts = [part for part in folder.split("/") if part not in ("", ".")]
    if not parts or ".." in parts or re.match(r"^[A-Za-z]:", folder):
        return None
    return "/".join(parts)


def parse_entries(text, root):
    #one comic per line: the folder it goes in and the page it starts from, in either order
    entries, problems = [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls = re.findall(r"https?://\S+", line)
        if len(urls) != 1:
            problems.append("line {0}: needs exactly one http(s) address".format(number))
            continue
        folder = clean_folder(line.replace(urls[0], " "))
        if folder is None:
            problems.append("line {0}: needs a folder inside the library, like Uncompressed/MyComic".format(number))
            continue
        if os.path.exists(os.path.join(root, *folder.split("/"), "mirror_metadata.json")):
            problems.append("line {0}: {1} is already in the library; update it instead".format(number, folder))
            continue
        entries.append((folder, urls[0].strip('"')))
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
                entries, problems = parse_entries(str(body.get("entries") or ""), args.root)
                try:
                    options = {
                        "prime": bool(body.get("prime")),
                        "prefix": bool(body.get("prefix")),
                        "increment": int(body.get("increment") or 1),
                        "javascript": bool(body.get("javascript")),
                        "waittime": int(body.get("waittime") or 0),
                        "cbz": body.get("cbz", True) is not False,
                        "direction_check": body.get("direction_check", True) is not False,
                    }
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
