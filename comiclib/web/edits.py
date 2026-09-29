#the changes the page can make: a comic's settings, the library's settings, and the chapter tools, which
#run chapters.py so that the page and the command line mean exactly the same thing by each.
import json
import os
import re
import subprocess
import sys
import time

from comiclib.metadata import write_json
from comiclib.web.adding import clean_folder
from comiclib.web.views import find_comic, is_running, read_metadata

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
    "multi_page": "flag",
    "ended": "flag",
}
max_edits = 50


def insert_page(args, comic, given):
    #a page the comic's own links skip past, put in where it belongs. it reads the page in a browser and
    #moves every file after it, so it takes minutes on a long comic rather than seconds.
    url = str(given.get("url") or "").strip()
    after = str(given.get("after") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        return 400, {"error": "the page to put in needs its full http(s) address"}
    if not after:
        return 400, {"error": "say which page it follows"}
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    command = [sys.executable, "-u", script, "insert", comic.folder, "--url", url, "--after", after]
    if args.root:
        command += ["--root", args.root]
    if given.get("dry_run"):
        command.append("--dry-run")
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=3600)
    except subprocess.SubprocessError as error:
        return 500, {"error": "could not put that page in: {0}".format(error)}
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    if done.returncode != 0:
        first = [line for line in output.splitlines() if line.strip().startswith("ERROR")]
        return 400, {"error": (first[0] if first else "that did not work")[:300],
                     "output": output[-4000:]}
    return 200, {"output": output[-8000:]}


def fix_chapter(args, comic, given):
    #one correction to one boundary, run through chapters.py so that the page and the command line mean
    #exactly the same thing by it. it takes a moment rather than a job: nothing is fetched and nothing is
    #written but the metadata.
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    command = [sys.executable, script, "fix", comic.folder, "--root", args.root]
    if given.get("clear"):
        command.append("--clear")
    else:
        at = str(given.get("at") or "").strip()
        if not at:
            return 400, {"error": "say which page the correction is about"}
        command += ["--at", at]
        if given.get("forget"):
            command.append("--forget")
        elif given.get("drop"):
            command.append("--drop")
        else:
            label = str(given.get("label") or "").strip()
            if not label:
                return 400, {"error": "say what the chapter starting there is called"}
            command += ["--label", label]
    try:
        #a correction on a comic whose archives are written rewrites the ones that changed, so this can
        #be a minute of zipping rather than a metadata edit
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=1800)
    except subprocess.SubprocessError as error:
        return 500, {"error": "could not work that out: {0}".format(error)}
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        return 400, {"error": output.strip().splitlines()[0] if output.strip() else "that did not work",
                     "output": output[-2000:]}
    return 200, {"output": output[-4000:]}


def try_chapter_list(args, comic, given):
    #reading an archive page and saying what it would be read as. it fetches one page and writes nothing,
    #so it answers "is this page usable" before a comic is committed to it - or walked for it.
    url = str(given.get("url") or "").strip()
    if not re.match(r"^https?://\S+$", url):
        return 400, {"error": "the chapter list has to be a full http(s) address"}
    like = str(given.get("like") or "").strip()
    if not comic and not re.match(r"^https?://\S+$", like):
        return 400, {"error": "give one of the comic's own page addresses, so its pages can be told "
                              "from everything else linked on that page"}
    script = os.path.join(os.path.dirname(os.path.abspath(args.script)), "chapters.py")
    command = [sys.executable, "-u", script, "try", comic.folder if comic else ".", "--archive", url]
    if like:
        command += ["--like", like]
    if given.get("browser"):
        command.append("--browser")
    if args.root:
        command += ["--root", args.root]
    began = time.time()
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), timeout=600)
    except subprocess.SubprocessError as error:
        return 500, {"error": "could not read that page: {0}".format(error)}
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    #a page that reads as nothing still has plenty to say about why, so its output is the answer either way
    return 200, {"output": output[-20000:], "seconds": int(time.time() - began),
                 "exit_code": done.returncode}


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

    #the chapter list is not a scraping setting, so it lives beside them rather than among them
    listing = given.get("chapters_url")
    if listing is not None:
        listing = str(listing).strip()
        if listing and not re.match(r"^https?://\S+$", listing):
            return 400, {"error": "the chapter list has to be a full http(s) address"}
        block = metadata.get("chapters") or {}
        if (block.get("source_url") or "") != listing:
            changed["chapters"] = [block.get("source_url"), listing or None]
            if listing:
                block["source"], block["source_url"] = "archive", listing
                block.setdefault("list", [])
                metadata["chapters"] = block
            elif block.get("list"):
                block["source_url"] = None
                metadata["chapters"] = block
            else:
                metadata.pop("chapters", None)

    if not changed:
        return 200, {"saved": False, "message": "nothing changed"}
    settings.update(cleaned)
    metadata["settings"] = settings
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    metadata["updated"] = stamp
    history = metadata.setdefault("history", {})
    history["edits"] = (history.get("edits") or [])[-(max_edits - 1):] + [{"at": stamp, "changed": changed}]

    #written beside the real file and swapped in, so a crash part way never leaves half a metadata file
    write_json(path, metadata)
    print("Edited {0}: {1}".format(comic.name, ", ".join(
        "{0} {1} -> {2}".format(key, json.dumps(old), json.dumps(new)) for key, (old, new) in changed.items())),
        flush=True)
    return 200, {"saved": True, "changed": changed, "updated": stamp}


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
