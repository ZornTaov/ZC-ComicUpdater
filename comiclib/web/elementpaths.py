#the element paths as the page shows and edits them: the shipped lists with their notes, laid under the
#library's own element_paths.json, and that file written back.
import ast
import json
import os
import re
import time

from comiclib.metadata import write_json

#the file mirror_base reads its element paths from, kept in the config folder so the container can write it
element_file = "element_paths.json"
kinds = ("image", "next")


def shipped_paths(script):
    #the lists as mirror_base has them, with the comment beside each one, if it has one, as a note. the
    #values are read as python rather than scanned for, because an xpath is full of brackets and quotes of
    #its own; the comments, which python throws away, are matched after.
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
