#the comics in a library: any folder holding a mirror_metadata.json, however deep the library groups them,
#and the scrape command each one resumes with.
import json
import os

from comiclib.metadata import METADATA_FILE as metadata_file, saved_command, settings_to_argv
from comiclib.pages import count as folder_pages


class Comic:
    #one folder holding pages, its metadata and the result of this run
    def __init__(self, folder, metadata, root=None):
        self.folder = folder
        #named by its path within the library, so grouped comics stay distinguishable in the summary
        self.name = os.path.relpath(folder, root).replace(os.sep, '/') if root else os.path.basename(folder)
        self.metadata = metadata
        self.argv = None
        self.code = None
        self.output = ""
        self.elapsed = 0.0
        #metadata written before page_count existed has no baseline, so count the folder instead of
        #treating it as empty and reporting the whole comic as newly gained
        count = (metadata.get("state") or {}).get("page_count", metadata.get("page_count"))
        if count is None:
            count = folder_pages(folder)
        self.before = count or 0
        self.after = self.before
        self.skipped = None
        #when this comic's process started, so a run in progress can say what it is still waiting on
        self.started_at = None
        #set when the saved command pointed at where this comic used to live
        self.moved_from = None
        #the running scraper and the last thing it said, so a run in progress can be watched and stopped
        self.process = None
        self.last_line = None
        self.stopped = False

    @property
    def gained(self):
        return max(self.after - self.before, 0)

    @property
    def ok(self):
        return self.code == 0


def find_comics(root, max_depth=5):
    #a comic is any folder holding a metadata file, so adding one is just scraping or adopting it once.
    #the search goes down through grouping folders, since a library often sorts comics by author or site,
    #but never descends past a comic: whatever a comic keeps inside it is its own business.
    comics = []
    root = os.path.abspath(root)
    for current, dirs, files in os.walk(root):
        depth = current[len(root):].count(os.sep)
        if metadata_file in files:
            dirs[:] = []
            meta_path = os.path.join(current, metadata_file)
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    comics.append(Comic(current, json.load(f), root))
            except (ValueError, OSError) as error:
                comic = Comic(current, {}, root)
                comic.skipped = "unreadable metadata: {0}".format(error)
                comics.append(comic)
            continue
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
    return sorted(comics, key=lambda c: c.name)


def resume_argv(comic):
    settings = comic.metadata.get("settings")
    if settings:
        argv = settings_to_argv(settings)
    else:
        #schema 1 kept the command itself rather than what it was made of. read it so an un-migrated
        #comic still runs, and it gets rewritten in the current shape the next time it is scraped
        argv = saved_command(comic.metadata)
    if not argv:
        return None

    #the metadata file's own location is what says where this comic lives, so an --output left over from
    #an earlier arrangement of the library is corrected rather than believed. trusting it would scrape the
    #comic into a fresh folder somewhere else and quietly leave the real one behind.
    for flag in ("--output", "-o"):
        if flag in argv:
            at = argv.index(flag) + 1
            if at < len(argv) and argv[at] != comic.name:
                comic.moved_from = argv[at]
                argv[at] = comic.name
            break
    return argv


def page_count(comic):
    #read the count back from the metadata the run just wrote, falling back to counting the folder
    try:
        with open(os.path.join(comic.folder, metadata_file), 'r', encoding='utf-8') as f:
            fresh = json.load(f)
            counted = (fresh.get("state") or {}).get("page_count", fresh.get("page_count"))
            if counted is not None:
                return counted
    except (ValueError, OSError):
        pass
    return folder_pages(comic.folder)
