#the rows of the add form turned into comics to scrape: where each one's pages and archive go inside the
#library, checked before anything is started.
import os
import re

from comiclib.metadata import METADATA_FILE


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
        if os.path.exists(os.path.join(args.root, *pages_at.split("/"), METADATA_FILE)):
            problems.append("row {0}: {1} is already in the library; update it instead".format(number, pages_at))
            continue
        entries.append((pages_at, archive_at, url, listing))
    seen = set()
    for pages_at, _, _, _ in entries:
        if pages_at in seen:
            problems.append("{0} is listed twice".format(pages_at))
        seen.add(pages_at)
    return entries, problems
