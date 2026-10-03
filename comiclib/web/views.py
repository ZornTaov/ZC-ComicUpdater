#what the page is shown: the library, one comic in detail, the jobs and how far each has got. reading
#only; nothing here changes a file.
import collections
import json
import os
import subprocess
import sys
import time

from comiclib import metadata as sidecar
from comiclib.chapters.index import reaches_newest, read_index


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
            "stopping": job.cancel.is_set(), "doing": job.doing if job.finished is None else None}
    if job.kind == "check":
        view["check"] = job.check
        return view
    if getattr(job, "outcome", None):
        view["outcome"] = job.outcome
    if getattr(job, "decide", None):
        view["decide"] = job.decide
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
            #whether that run followed the comic to its end. a primed comic exits cleanly having saved one
            #page, which is not the same thing as having nothing left to fetch
            "completed": last.get("completed"),
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
    metadata = sidecar.load(path)
    #an old sidecar is brought up to date first, so the edit lands in the one place a run reads it
    fresh = sidecar.migrate(metadata)
    if not fresh:
        return metadata
    #but only read, it has not been rewritten, so it keeps the file's own stamp. the migration stamps the
    #time it ran, and an editor that opened it one second and saved it the next was told it had changed
    #under them when nothing had
    fresh["updated"] = metadata.get("updated")
    return fresh


def index_pages(args, uc, comic):
    #how many pages this comic's record of which-page-is-which holds. counted rather than trusted, since
    #the file is written a line at a time as a walk goes and can stop anywhere
    named = ((comic.metadata.get("history") or {}).get("index_cache"))
    if not named:
        return 0
    path = os.path.join(uc.config_folder(), "index", named)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def primed(lines, history, reaches):
    #one line that is the comic's first page, recorded as page one, and the newest page it has saved. a
    #walk begun on the newest page fails the first of those, since its one line is the newest, not the first
    history = history if isinstance(history, dict) else {}
    return (len(lines) == 1 and reaches is True and lines[0].get("n") == 1
            and history.get("first_page_number") in (0, 1)
            and bool(history.get("first_page_url")) and lines[0].get("url") == history["first_page_url"])


def walk_needed(args, uc, comic):
    #whether working out chapters has to walk the comic first: "start" when nothing records which page is
    #which, "carry on" when the record stops short of the comic's newest page, None when it reaches it.
    #a record's being there says nothing about how far it got - a walk the site cut off part way leaves
    #thousands of lines short of the comic - so it is asked whether it holds the newest page saved
    named = ((comic.metadata.get("history") or {}).get("index_cache"))
    if not named:
        return "start"
    try:
        lines = read_index(os.path.join(uc.config_folder(), "index", named))
    except (OSError, ValueError):
        return "start"
    #a record of a single page is usually a walk that never happened: started on the comic's newest page,
    #found no next link there, and wrote that one page down. a primed comic's is the other kind - its first
    #page, the only one it has saved yet - and is the whole of what it holds, which the update fetching the
    #rest adds to. walking it now would fetch every page that update is about to fetch anyway
    reaches = reaches_newest(lines, comic.metadata.get("state"))
    if len(lines) < 2 and not primed(lines, comic.metadata.get("history"), reaches):
        return "start"
    if reaches is False:
        return "carry on"
    return None


def chapters_label(name):
    #what a job working out a comic's chapters is called, which is also how its last one is found again
    return "Work out chapters for {0}".format(name)


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
    chapters = metadata.get("chapters") or {}
    indexed_pages = index_pages(args, uc, comic)
    #the newest time working out its chapters stopped to ask, unless something about its chapters has run
    #since - answered, or worked out some other way - when the question no longer stands
    asked = None
    for job in runner.recent:
        if job.get("kind") == "chapters" and job.get("label") == chapters_label(comic.name):
            asked = job.get("decide")
            break
    return {
        "name": comic.name,
        "updated": metadata.get("updated"),
        "settings": metadata.get("settings") or {},
        "chapters": {"source_url": chapters.get("source_url"), "count": len(chapters.get("list") or []),
                     "packed": chapters.get("packed"), "folder": chapters.get("folder"),
                     "source": chapters.get("source"), "every": chapters.get("every"),
                     "list": chapters.get("list") or [],
                     "fixes": chapters.get("fixes") or []},
        "indexed": bool((metadata.get("history") or {}).get("index_cache")),
        #how much of the comic that record actually covers. a comic with a record of one page has been
        #walked in name only, and saying the number is what makes that visible
        "indexed_pages": indexed_pages,
        #a record there is, but one that a walk never got past the first page of: it says nothing, and
        #stands in the way of cutting by the file numbers until it is discarded
        "stale_walk": indexed_pages > 0 and walk_needed(args, uc, comic) == "start",
        "decide": asked,
        "state": metadata.get("state") or {},
        "first_page_url": history.get("first_page_url"),
        "runs": [{key: run.get(key) for key in ("started", "start_url", "start_page_number", "last_url",
                                                "last_page_number", "pages_saved", "stop_reason", "exit_code")}
                 for run in runs[-8:]][::-1],
        "edits": (history.get("edits") or [])[-8:][::-1],
        "pages_in_folder": uc.folder_pages(comic.folder),
        "running": is_running(runner, comic.name),
    }, None


def walked_pages(args, comic):
    #every page the walk saw, so a boundary can be picked from the comic itself rather than typed. a
    #comic that has never been walked simply has none, which the page says rather than pretending.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    command = [sys.executable, "-u", script, "show", comic.folder, "--json"]
    if args.root:
        command += ["--root", args.root]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=300)
    except subprocess.SubprocessError as error:
        return 500, {"error": "could not read the walk: {0}".format(error)}
    if done.returncode != 0:
        #not an error worth a red box: it only means nobody has walked this comic yet
        return 200, {"pages": [], "walked": False,
                     "why": (done.stdout or done.stderr or "").strip()[:200]}
    try:
        held = json.loads(done.stdout)
    except ValueError:
        return 500, {"error": "the walk could not be read back"}
    pages = held.get("pages") or []
    #every page of one comic carries the same site name in its title, which says nothing about the page
    titles = [str(page.get("title") or "") for page in pages if page.get("title")]
    shared = 0
    if len(titles) > 1:
        first, last = min(titles), max(titles)
        while shared < len(first) and shared < len(last) and first[shared] == last[shared]:
            shared += 1
        if shared < 4:
            shared = 0
    for page in pages:
        said = str(page.get("title") or "")
        page["short"] = (said[shared:] if shared and len(said) > shared else said).strip(" -|:–")
    return 200, {"pages": pages, "walked": True, "settled": bool(held.get("settled"))}


def config_view(args, uc):
    saved = uc.load_config(quiet=True)
    return {"path": uc.config_path(), "saved": os.path.exists(uc.config_path()),
            "settings": saved, "defaults": uc.config_defaults,
            "restart_needed": ["schedule"], "root": args.root,
            "from_command_line": sorted(getattr(args, "from_command_line", []))}
