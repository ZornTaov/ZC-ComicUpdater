#what the info page shows of a comic: what its ComicInfo says it is, where it came from on the web, where it
#is kept, and how its last update went. read from the comic's own metadata where it has a folder, and from
#the copy packed into its archive where it has only that - an archive the scraper made carries one
import os

from comiclib.metadata import migrate, read as read_metadata

#what a ComicInfo can say that the page shows, in the order it shows it
SHOWN = ("title", "series", "number", "count", "volume", "summary", "year", "writer", "penciller", "genre",
         "tags", "web")


def metadata_of(comic, stream):
    if comic.get("folder"):
        found = read_metadata(comic["folder"])
        if found:
            return migrate(found) or found
    return stream.get("metadata") or {}


def chapter_of(comic, metadata):
    #the chapter a comic packed one archive per chapter is, in its metadata's list of them
    if not comic.get("parent") or not comic.get("number"):
        return None
    for chapter in (metadata.get("chapters") or {}).get("list") or []:
        if str(chapter.get("number")) == str(comic["number"]):
            return chapter
    return None


def links(comic, metadata, about):
    #every address there is for the comic, the most useful first, each once. the first page is the comic
    #itself; the address an update carries on from is where it is up to on the site
    settings, history = metadata.get("settings") or {}, metadata.get("history") or {}
    chapter = chapter_of(comic, metadata)
    found = []
    if chapter and chapter.get("start_url"):
        found.append(("This chapter's first page", chapter["start_url"]))
    found.append(("The comic's first page", history.get("first_page_url")))
    found.append(("Where updates carry on from", settings.get("url")))
    found.append(("The archive's web address", about.get("web")))
    found.append(("The chapter list", (metadata.get("chapters") or {}).get("source_url")))
    out, seen = [], set()
    for label, url in found:
        if url and url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            out.append({"label": label, "url": url})
    return out


def last_run(metadata):
    runs = (metadata.get("history") or {}).get("runs") or []
    if not runs:
        return None
    run = runs[-1]
    return {key: run.get(key) for key in ("updated", "pages_saved", "completed", "stop_reason", "exit_code")}


def describe(library, comic):
    stream = library.stream(comic, fresh=True)
    metadata = metadata_of(comic, stream)
    about = stream["about"]
    root = library.config.library

    def shown(path):
        return os.path.relpath(path, root).replace(os.sep, "/") if path else None
    #called and covered as the library shelf has it, so the page and the shelf agree
    summary = library.summary(comic, None)
    return {
        "id": comic["id"], "title": summary["title"], "name": summary["name"], "author": summary["author"],
        "cover": summary["cover"], "coverChosen": summary["coverChosen"], "kind": comic["kind"], "place": comic.get("place", ""),
        "pages": len(stream["pages"]), "ended": stream["ended"],
        "about": {key: about[key] for key in SHOWN if about.get(key)},
        #what was said about it by hand, as its metadata keeps it: what an edit starts from
        "said": metadata.get("info") or {},
        #a comic the scraper keeps up to date, rather than an archive from somewhere else
        "scraped": bool(comic.get("folder")),
        "links": links(comic, metadata, about),
        "folder": shown(comic.get("folder")),
        "files": [shown(path) for path in comic["sources"]],
        "pageCount": (metadata.get("state") or {}).get("page_count"),
        "lastRun": last_run(metadata),
        #what an edit is checked against, so one made over a change it never saw is refused: the metadata's
        #stamp for a comic the scraper keeps, the archive's version for one from elsewhere
        "updated": metadata.get("updated"),
        "version": stream["versions"][0] if stream["versions"] else None,
        #whether the page offers to change what it says
        "editable": bool(comic.get("folder")) or (comic["kind"] == "archive" and len(comic["sources"]) == 1),
    }
