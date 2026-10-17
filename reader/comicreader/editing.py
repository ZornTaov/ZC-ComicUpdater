#what the info page changes: what a comic is said to be, written where it will last. a comic the scraper keeps
#has it written into its metadata's info block - which the scraper writes into every ComicInfo it makes from
#then on - and its archives' ComicInfo brought up to it at once. an archive from somewhere else, with no
#metadata to keep it in, has its own ComicInfo changed, and everything else it says is left as it was.
#
#a folder or a series is changed the same way, a comic at a time, but only what was changed on the page: a
#box left saying "mixed" leaves each comic saying what it did.
#
#nothing is written while the scraper may be writing the same comic: during an update of the library, or
#while the comic's last run or its archives changed only moments ago
import calendar
import os
import threading
import time
import zipfile
from contextlib import contextmanager

from comiclib import cbz, comicinfo
from comiclib.chapters.numbering import numbered, written
from comiclib.metadata import METADATA_FILE, migrate, now_stamp, read as read_metadata, write_json

from comicreader.library import CHAPTER

#how long after the scraper last touched a comic it is left alone: a scrape writes its metadata after every
#page, and a slow site can take a while over one
QUIET = 300
#what update_comics holds while it updates the library
LOCK = ".update_comics.lock"
#what may be said of a whole folder or series at once: everything but the title, which is each comic's own
SHARED = tuple(key for key in comicinfo.INFO + comicinfo.EXTRA if key != "title")


class Refused(Exception):
    #why the change was not made, said as what to do about it, with the status the page is answered with
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def took(seconds):
    return "{0:.1f}s".format(seconds) if seconds < 60 else "{0}m{1:02d}s".format(int(seconds // 60), int(seconds % 60))


class Underway:
    #the one edit being written, and how far it has got. a comic kept in chapters has every chapter archive
    #written, and one of a hundred chapters takes minutes, so the page asks this to show it is still going.
    #a second edit is refused until the first is done, rather than written into the same archives beside it
    def __init__(self):
        self.lock = threading.Lock()
        self.now = None

    def state(self):
        now = self.now
        if now is None:
            return None
        return dict(now, seconds=round(time.time() - now["started"], 1))

    @contextmanager
    def doing(self, what):
        if not self.lock.acquire(blocking=False):
            now = self.now or {}
            raise Refused(409, "{0} is still being written ({1} of {2} archives so far). Try again once it has "
                               "finished.".format(now.get("what", "Another change"), now.get("done", 0),
                                                  now.get("total", 0)))
        #total is 0 while what is to be written is still being checked
        self.now = {"what": what, "done": 0, "total": 0, "told": 0, "at": None, "started": time.time()}
        try:
            yield self.now
        finally:
            self.now = None
            self.lock.release()

    def step(self, path):
        #an archive about to be written
        if self.now is not None:
            self.now["at"] = os.path.basename(path)

    def stepped(self):
        if self.now is not None:
            self.now["done"] += 1


def stamp(path):
    found = os.stat(path)
    return (found.st_size, found.st_mtime_ns)


def ago(seconds):
    return "{0} seconds".format(int(seconds)) if seconds < 120 else "{0} minutes".format(int(seconds // 60))


def wait_for_quiet(library, paths, last_run):
    #refused while the scraper may be writing: an update of the whole library holds a lock, and a comic
    #updated on its own leaves its last run's time, and its archive's, only moments ago. an archive the
    #reader wrote itself is no sign of the scraper
    if os.path.exists(os.path.join(library.config.library, LOCK)):
        raise Refused(409, "The library is being updated right now. Try again once the update has finished.")
    now = time.time()
    if last_run:
        try:
            since = now - calendar.timegm(time.strptime(last_run, "%Y-%m-%dT%H:%M:%SZ"))
        except (TypeError, ValueError):
            since = QUIET
        if since < QUIET:
            raise Refused(409, "This comic was being updated {0} ago and may still be. Try again in a few "
                               "minutes.".format(ago(max(since, 0))))
    for path in paths:
        try:
            found = stamp(path)
        except OSError:
            continue
        if library.written.get(path) == found:
            continue
        since = now - found[1] / 1e9
        if since < QUIET:
            raise Refused(409, "{0} changed {1} ago and may still be being written. Try again in a few "
                               "minutes.".format(os.path.basename(path), ago(max(since, 0))))


def writing(action):
    #a library mounted read-only refuses every write: said as what to change, not as an error
    try:
        return action()
    except OSError as error:
        if getattr(error, "errno", None) in (13, 30):
            raise Refused(503, "The reader cannot write to the library: it is mounted read-only, or not owned "
                               "by the reader's user. Mount it read-write to edit what a comic says.")
        raise


def retell(library, path, folder, about, keep_metadata):
    #a ComicInfo put on the end of the archive, as a scrape's append puts one: the pages stay where they are
    before = stamp(path)
    names = sorted(name for name in os.listdir(folder) if name != METADATA_FILE)
    change = cbz.planned(path, folder, names, (), about, adding=False)
    if not change["retold"]:
        return False
    if stamp(path) != before:
        raise Refused(409, "{0} changed while it was being looked at. Try again in a few minutes.".format(
            os.path.basename(path)))
    writing(lambda: cbz.apply(path, folder, change, metadata=keep_metadata))
    library.written[path] = stamp(path)
    return True


def chapter_archives(library, comic, metadata):
    #every chapter archive of a comic packed one per chapter, each with the chapter its metadata lists. an
    #archive is named by its chapter's own number, the same one the scraper works out from the labels
    listed = {written(chapter["called"]): chapter for chapter in numbered(metadata.get("chapters"))}
    out = []
    for each in library.comics.values():
        if each.get("parent") != comic["parent"]:
            continue
        found = CHAPTER.match(os.path.basename(each["sources"][0]))
        chapter = listed.get(written(found.group("number"))) if found else None
        if chapter:
            out.append((each["sources"][0], chapter))
    return out, len(listed)


def archives_of(library, comic, metadata):
    #every archive of a comic the scraper keeps, each with what makes its about and whether the archive
    #carries the metadata too: one per chapter for a comic packed in chapters, else its one archive
    folder = comic["folder"]
    if comic.get("parent"):
        chapters, count = chapter_archives(library, comic, metadata)
        return [(archive, lambda m, chapter=chapter: comicinfo.about_chapter(folder, m, chapter, count), False)
                for archive, chapter in chapters]
    if comic["kind"] == "archive":
        return [(comic["sources"][0], lambda m: comicinfo.about_comic(folder, m), True)]
    return []


def scraped_plan(library, comic, updated):
    #what changing a comic the scraper keeps will write, read and checked before anything is
    folder = comic["folder"]
    metadata = read_metadata(folder)
    if not metadata:
        raise Refused(409, "{0}'s metadata could not be read, so nothing was changed.".format(
            os.path.basename(folder)))
    metadata = migrate(metadata) or metadata
    if updated is not None and metadata.get("updated") != updated:
        raise Refused(409, "{0} was changed since the page was opened. Reload it and make the change again.".format(
            os.path.basename(folder)))
    runs = (metadata.get("history") or {}).get("runs") or []
    plan = {"folder": folder, "path": os.path.join(folder, METADATA_FILE), "metadata": metadata,
            "archives": archives_of(library, comic, metadata)}
    wait_for_quiet(library, [archive for archive, _, _ in plan["archives"]], runs[-1].get("updated") if runs else None)
    return plan


def scraped_write(library, plan, info, work):
    metadata = plan["metadata"]
    if info:
        metadata["info"] = info
    else:
        metadata.pop("info", None)
    metadata["updated"] = now_stamp()
    writing(lambda: write_json(plan["path"], metadata))
    told = 0
    for archive, about, whole in plan["archives"]:
        work.step(archive)
        if os.path.isfile(archive) and retell(library, archive, plan["folder"], about(metadata), whole):
            told += 1
        work.stepped()
    return told


def version_of(path):
    #what the page was shown an archive from elsewhere as, so a change made over another it never saw is refused
    return "{0:x}{1:x}".format(*stamp(path))[-12:]


def archive_plan(library, comic, version):
    path = comic["sources"][0]
    if version is not None and version != version_of(path):
        raise Refused(409, "{0} was changed since the page was opened. Reload it and make the change again.".format(
            os.path.basename(path)))
    wait_for_quiet(library, [path], None)
    return path


def archive_write(library, path, changes, work):
    work.step(path)
    try:
        return archive_retold(library, path, changes)
    finally:
        work.stepped()


def archive_retold(library, path, changes):
    #an archive from somewhere else: its own ComicInfo, changed where the page changed it and nowhere else
    before = stamp(path)
    with zipfile.ZipFile(path) as zf:
        try:
            had = zf.read(comicinfo.NAME)
        except KeyError:
            had = None
    body = comicinfo.retold(had, changes)
    if body is None:
        raise Refused(409, "{0}'s ComicInfo.xml cannot be read, so it was left as it is.".format(
            os.path.basename(path)))
    if body == had:
        return 0
    if stamp(path) != before:
        raise Refused(409, "{0} changed while it was being looked at. Try again in a few minutes.".format(
            os.path.basename(path)))
    writing(lambda: cbz.apply(path, None, {"prefix": "", "added": [], "stale": [], "info": body}, metadata=False))
    library.written[path] = stamp(path)
    return 1


def sayable(said):
    if not isinstance(said, dict):
        raise Refused(400, "info should be an object of what the comic is said to be.")
    problems = comicinfo.unsayable(said)
    if problems:
        raise Refused(400, "; ".join(problems) + ".")
    return said


def called(comic):
    #what the log calls a comic: a chapter archive's title is its chapter's, so a comic the scraper keeps
    #goes by its folder
    return os.path.basename(comic["folder"]) if comic.get("folder") else os.path.basename(comic["sources"][0])


@contextmanager
def logged(work, what, fields):
    #the log says an edit began and how it ended: one of a comic in a hundred chapters runs for minutes, and
    #said nothing at all while it did
    began = time.time()
    with work.doing(what) as now:
        try:
            yield now
        except Refused as refused:
            print("ComicInfo of {0} not written: {1}".format(what, refused), flush=True)
            raise
        except Exception as error:
            print("ComicInfo of {0} failed after {1} of {2} archives: {3}".format(
                what, now["done"], now["total"], error), flush=True)
            raise
    print("ComicInfo of {0} written ({1}): {2} of {3} archives in {4}".format(
        what, ", ".join(fields), now["told"], now["total"], took(time.time() - began)), flush=True)


def begun(now, what, fields):
    #an edit of one archive is over too soon to need saying it began
    if now["total"] > 1:
        print("ComicInfo of {0}: writing {1} into {2} archives".format(what, ", ".join(fields), now["total"]),
              flush=True)


def edit(library, comic, body, work=None):
    #the nine are always on the form, so one left out is one emptied. the rest of the schema changes only
    #where it is named, "" taking it out: a page from before it could say them sends only the nine, and must
    #not take out a publisher it never showed
    work = work or Underway()
    said = sayable(body.get("info") or {})
    info = comicinfo.clean_info(said)
    named = comicinfo.INFO + tuple(tag for tag in comicinfo.EXTRA if tag in said)
    if not comic.get("folder") and not (comic["kind"] == "archive" and len(comic["sources"]) == 1):
        raise Refused(409, "This comic is kept as chapter archives from somewhere else; each can be changed from "
                           "its own info page.")
    what = called(comic)
    fields = sorted(said) or ["nothing"]
    with logged(work, what, fields) as now:
        if comic.get("folder"):
            plan = scraped_plan(library, comic, body.get("updated"))
            now["total"] = len(plan["archives"])
            begun(now, what, fields)
            kept = {key: value for key, value in (plan["metadata"].get("info") or {}).items() if key not in named}
            now["told"] = scraped_write(library, plan, comicinfo.clean_info(dict(kept, **info)), work)
        else:
            path = archive_plan(library, comic, body.get("version"))
            now["total"] = 1
            now["told"] = archive_write(library, path, {key: info.get(key) for key in named}, work)
    return now["told"]


def gather(library, ids):
    #the comics a folder or series holds, each once as what an edit is made to: a comic the scraper keeps
    #once however many chapter archives it is shelved as, an archive from elsewhere on its own
    found, seen = [], set()
    for comic_id in ids if isinstance(ids, list) else []:
        comic = library.comics.get(str(comic_id))
        if comic is None:
            continue
        if comic.get("folder"):
            key = comic["folder"]
        elif comic["kind"] == "archive" and len(comic["sources"]) == 1:
            key = comic["sources"][0]
        else:
            continue
        if key not in seen:
            seen.add(key)
            found.append(comic)
    if not found:
        raise Refused(404, "None of those comics is in the library any more. Refresh the library and try again.")
    return found


def comicinfo_in(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.read(comicinfo.NAME)
    except (OSError, KeyError, zipfile.BadZipFile):
        return b""


def describe_many(library, ids):
    #what a folder or series says now, field by field: what every comic in it says, or that they differ.
    #a comic the scraper keeps is read from its metadata - what its archives are made from - and not opened
    each = []
    for comic in gather(library, ids):
        if comic.get("folder"):
            found = read_metadata(comic["folder"]) or {}
            metadata = migrate(found) or found
            said = comicinfo.said_by(comicinfo.about_comic(comic["folder"], metadata))
            each.append({"id": comic["id"], "said": said, "stamp": metadata.get("updated"), "scraped": True,
                         "archives": len(archives_of(library, comic, metadata))})
        else:
            path = comic["sources"][0]
            each.append({"id": comic["id"], "said": comicinfo.said_in(comicinfo_in(path)),
                         "stamp": version_of(path), "scraped": False, "archives": 1})
    fields = {}
    for key in SHARED:
        values = [str(one["said"].get(key, "")) for one in each]
        if key in comicinfo.INFO or any(values):
            same = all(value == values[0] for value in values)
            fields[key] = {"value": values[0] if same else None, "mixed": not same}
    return {"comics": len(each), "scraped": sum(1 for one in each if one["scraped"]),
            "archives": sum(one["archives"] for one in each), "fields": fields,
            "stamps": {one["id"]: one["stamp"] for one in each}, "form": comicinfo.form()}


def edit_many(library, body, work=None):
    #only what was changed, in every comic: a value said of each, or "" taking it out of each. every comic is
    #checked before any is written, so one the scraper is busy with refuses the lot rather than half of it
    work = work or Underway()
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise Refused(400, "Nothing was changed, so nothing was written.")
    wrong = [key for key in changes if key not in SHARED]
    if wrong:
        raise Refused(400, "{0} cannot be said of a whole folder or series at once; change it on each comic's "
                           "own info page.".format(", ".join(comicinfo.label(key) for key in wrong)))
    sayable(changes)
    cleaned = {key: comicinfo.fit(key, value) if value is not None else None for key, value in changes.items()}
    stamps = body.get("stamps") if isinstance(body.get("stamps"), dict) else {}
    comics = gather(library, body.get("ids"))
    what = called(comics[0]) if len(comics) == 1 else "{0} comics".format(len(comics))
    fields = sorted(changes)
    with logged(work, what, fields) as now:
        planned = []
        for comic in comics:
            if comic.get("folder"):
                planned.append((True, scraped_plan(library, comic, stamps.get(comic["id"]))))
            else:
                planned.append((False, archive_plan(library, comic, stamps.get(comic["id"]))))
        now["total"] = sum(len(plan["archives"]) if scraped else 1 for scraped, plan in planned)
        begun(now, what, fields)
        for scraped, plan in planned:
            if scraped:
                info = dict(plan["metadata"].get("info") or {})
                for key, value in cleaned.items():
                    if value is None:
                        info.pop(key, None)
                    else:
                        info[key] = value
                now["told"] += scraped_write(library, plan, comicinfo.clean_info(info), work)
            else:
                now["told"] += archive_write(library, plan, cleaned, work)
    return {"comics": len(planned), "told": now["told"]}
