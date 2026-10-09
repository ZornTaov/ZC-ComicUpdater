#mirror_metadata.json: the one file in each comic's folder that says everything about it. its settings
#block is the only thing anyone edits; the scrape command is rebuilt from it every run.
import json
import os
import shlex
from datetime import datetime, timezone

METADATA_FILE = "mirror_metadata.json"
SCHEMA = 2


def now_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def load(path):
    #the file itself, raising when it cannot be read, for a caller that has something to say about that
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read(folder):
    #a comic's metadata, or nothing, for a caller that carries on either way
    try:
        return load(os.path.join(folder, METADATA_FILE))
    except (OSError, ValueError):
        return {}


def write_json(path, body, indent=2):
    #written beside the real file and moved into place, so a run stopped part way never leaves half a file
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    spare = path + ".writing"
    with open(spare, 'w', encoding='utf-8') as f:
        json.dump(body, f, indent=indent)
        f.write('\n')
    os.replace(spare, path)


def write(folder, metadata):
    write_json(os.path.join(folder, METADATA_FILE), metadata)


def settings_to_argv(settings):
    #the single place a scrape command is built. the metadata records what a comic needs as plain values,
    #not as a command, so this is the only thing that has to know which value is which flag - and editing
    #one value in the file is the whole of changing how a comic is scraped.
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
    #likewise: saving every page an address holds is the default, and only a comic told to read one page
    #an address regardless needs the flag carried forward
    if settings.get("multi_page") is False:
        argv.append("--no-multi-page")
    if settings.get("cbz_path"):
        argv += ["--cbz-path", settings["cbz_path"]]
    argv.append(url)
    return argv


def argv_to_settings(argv):
    #the inverse of settings_to_argv, for reading a schema 1 sidecar that saved the command itself rather
    #than what it was made of. flags that describe the machine rather than the comic - chrome, headless,
    #verbose - are deliberately dropped rather than pinned into a comic's settings.
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
        elif token == "--no-multi-page":
            settings["multi_page"] = False
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


def saved_command(old):
    #the scrape command a schema 1 file kept, as the arguments after the script's own name
    argv = old.get("resume_argv")
    if argv:
        return list(argv)
    command = old.get("resume_command_line")
    if not command:
        return None
    argv = shlex.split(command)
    #drop the leading "python mirror_base.py"
    while argv and (argv[0].startswith('python') or argv[0].endswith('.py')):
        argv.pop(0)
    return argv


def migrate(old):
    #schema 1 wrote the resume command three times over - as a list, as a string, and again inside every
    #run entry - with no plain value anywhere for things like prefix. this pulls the command apart into
    #the settings block that replaced it, so the facts have one home and editing one is enough. none when
    #the file is already current.
    if old.get("schema", 1) >= SCHEMA:
        return None
    settings = argv_to_settings(saved_command(old))

    #a comic marked ended has no resume command at all, so everything has to come from the flat keys
    if not settings["url"]:
        settings["url"] = old.get("source_url") or old.get("last_page_url")
    if not settings["output"]:
        settings["output"] = old.get("output_folder")
    if not settings["cbz_path"]:
        settings["cbz_path"] = old.get("archive_path")
    if settings["increment"] is None:
        for key in ("resume_page_number", "last_page_number", "page_count"):
            if old.get(key) is not None:
                settings["increment"] = old[key]
                break
    settings["ended"] = bool(old.get("ended", False))

    #run history keeps the argv that is the actual record of what ran, and loses the rendered command and
    #the option dump that said the same thing twice more
    runs = [{k: v for k, v in run.items() if k not in ("command_line", "options")}
            for run in old.get("runs", [])]

    fresh = {
        "schema": SCHEMA,
        "generator": old.get("generator", "adopt_comic.py"),
        "generator_version": old.get("generator_version"),
        "created": old.get("created", now_stamp()),
        "updated": now_stamp(),
        "settings": settings,
        "state": {
            "site": old.get("site"),
            "page_count": old.get("page_count"),
            "completed": bool(old.get("completed", False)),
            "image_xpath": old.get("image_xpath"),
            "next_xpath": old.get("next_xpath"),
            "last_image_url": old.get("last_image_url"),
            "last_image_file": old.get("last_image_file"),
        },
        "history": {
            "first_page_url": old.get("first_page_url"),
            "first_page_number": old.get("first_page_number"),
            "adopted": bool(old.get("adopted", False)),
            "runs": runs,
        },
    }
    if old.get("adopted_from"):
        fresh["history"]["adopted_from"] = old["adopted_from"]
    #where the chapters are: written by chapters.py into whatever schema the file was in, so a schema 1 file
    #can hold them. they describe the comic, not how its metadata was once written, and are carried across
    #as a scrape carries them - dropped, the comic's chapter archives would be read as a comic of their own
    if old.get("chapters"):
        fresh["chapters"] = old["chapters"]
    return fresh
