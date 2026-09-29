#the scan as a spreadsheet to fill in, and read back: a library of comics is adopted a row at a time, and
#whatever was already typed in survives the scan being run again.
import argparse
import csv
import os

from comiclib.adopt.scan import every_archive, matching_archive, relative_output

#the report's columns. the first block is what the scan worked out and is there to read; the second is
#what you fill in. a row is adopted once it has an address or is marked ended, and ignored until then.
report_columns = [
    "path", "kind", "pages", "numbering", "last_number", "nested",
    "last_url", "next_url", "ended", "increment", "prefix", "cbz_path", "notes",
]
editable_columns = ["last_url", "next_url", "ended", "increment", "prefix", "cbz_path", "notes"]


def truthy(text):
    return str(text or "").strip().lower() in ("y", "yes", "true", "1", "x", "t")


def write_report(rows, path, root, keep_edits=True):
    #re-running the report keeps whatever was already typed in, so a migration can be picked up later
    previous, by_name = {}, {}
    if keep_edits and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                for old in csv.DictReader(f):
                    was_at = old.get("path", "")
                    previous[was_at] = old
                    by_name.setdefault(os.path.basename(was_at).lower(), []).append(old)
        except (OSError, csv.Error):
            pass

    archives = every_archive(root)
    folder_paths = [item for item, kind, _, _ in rows if kind == "folder"]
    #two archives sharing a name are usually one file kept in two places; worth pointing out rather than
    #silently picking one
    twice = {name for name, found in archives.items() if len(found) > 1}
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=report_columns)
        writer.writeheader()
        for item, kind, details, nested in rows:
            rel = relative_output(item, root)
            was = previous.get(rel)
            if was is None:
                #a library gets reorganised; falling back to the comic's own name keeps the answers that
                #were typed in against its old location, as long as the name still picks out one comic
                same = by_name.get(os.path.basename(rel).lower(), [])
                was = same[0] if len(same) == 1 else None
            if was is None:
                #a folder that used to be listed as one row may now be listed as its separate files, so
                #what was answered for the folder still applies to everything that was inside it
                parent = by_name.get(os.path.basename(os.path.dirname(rel)).lower(), [])
                was = dict(parent[0], cbz_path="") if len(parent) == 1 else {}
            row = {
                "path": rel,
                "kind": kind,
                "pages": (details or {}).get("count", ""),
                "numbering": (details or {}).get("style", ""),
                "last_number": (details or {}).get("last_number", ""),
                "nested": nested or "",
            }
            for column in editable_columns:
                row[column] = was.get(column, "")
            #a kept archive path that no longer points anywhere is left over from how the library used to
            #be arranged, so it is paired again. one that matches nothing is kept as typed, to be seen and
            #corrected rather than quietly dropped.
            stale = row["cbz_path"] and not os.path.isfile(
                os.path.join(root, row["cbz_path"].replace('/', os.sep)))
            if kind == "folder" and (not row["cbz_path"] or stale):
                row["cbz_path"] = matching_archive(item, root, archives, folder_paths) or row["cbz_path"]
            if not row["notes"] and kind == "cbz x":
                row["notes"] = "several archives here; point a row at one file to adopt it"
            if not row["notes"] and kind == "cbz" and os.path.basename(item)[:-4].lower() in twice:
                row["notes"] = "another archive in the library has this same name"
            writer.writerow(row)
    return len(rows)


def read_report(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return [row for row in csv.DictReader(f)]


def row_to_args(row, base):
    #turns one filled-in report line into the same arguments a single adopt call would take
    args = argparse.Namespace(**vars(base))
    args.path = os.path.join(base.root, row.get("path", "").replace('/', os.sep))
    args.last_url = (row.get("last_url") or "").strip() or None
    args.next_url = (row.get("next_url") or "").strip() or None
    args.ended = truthy(row.get("ended"))
    args.cbz_path = (row.get("cbz_path") or "").strip() or None
    increment = (row.get("increment") or "").strip()
    args.increment = int(increment) if increment.isdigit() else None
    prefix = (row.get("prefix") or "").strip()
    args.prefix = None if not prefix else truthy(prefix)
    return args
