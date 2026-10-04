#the element paths as the page shows and edits them: the shipped lists with their notes, laid under the
#library's own element_paths.json, and that file written back.
import json
import os
import time

from comiclib.elements import kinds, shipped
from comiclib.metadata import write_json

#the file mirror_base reads its element paths from, kept in the config folder so the container can write it
element_file = "element_paths.json"


def shipped_paths():
    #the lists every scrape starts from, already laid out as the saved file is, copied so nothing the page
    #does to them reaches the ones a scrape reads
    return {kind: [dict(entry) for entry in shipped[kind]] for kind in kinds}


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
    built_in = shipped_paths()
    lists = {}
    for kind in kinds:
        from_shipped = {entry["xpath"]: entry.get("note", "") for entry in built_in[kind]}
        seen, ordered = set(), []
        for entry in saved.get(kind) or []:
            xpath = (entry or {}).get("xpath")
            if not xpath or xpath in seen:
                continue
            seen.add(xpath)
            ordered.append({"xpath": xpath, "note": entry.get("note") or from_shipped.get(xpath, ""),
                            "enabled": entry.get("enabled", True), "shipped": xpath in from_shipped})
        #anything the file never mentioned is still live, and mirror_base puts it after what the file lists
        ordered += [{"xpath": entry["xpath"], "note": entry.get("note", ""), "enabled": True, "shipped": True}
                    for entry in built_in[kind] if entry["xpath"] not in seen]
        lists[kind] = ordered
    return dict(lists, path=path, saved=bool(saved), problem=problem)


def save_elements(args, uc, given):
    cleaned, problems = {}, []
    for kind in kinds:
        if kind not in given:
            #a page loaded before this kind of path existed sends nothing for it. that is not a list with
            #everything turned off, so whatever is saved for it now is kept as it is
            cleaned[kind] = [{"xpath": entry["xpath"], "note": entry["note"], "enabled": entry["enabled"]}
                             for entry in element_settings(args, uc)[kind]]
            continue
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
    print("Saved {0}: {1} image path(s), {2} next path(s), {3} first-page path(s)".format(
        path, *(len([e for e in cleaned[kind] if e["enabled"]]) for kind in kinds)), flush=True)
    return 200, {"saved": True, "path": path}
