# Working on this project

Notes for whoever picks this up next, written down because they were worked out the slow way more than
once. The README is the user-facing documentation and is thorough — read it for *what* the tools do.
This file is about *how the pieces fit* and *what is easy to get wrong*.

Paths on any particular machine — which drive the library is on, where the container folder is mounted —
are deliberately **not** in this file, since it is tracked. They belong in local notes.

## What this is

Five scripts, and the package they share, that mirror webcomics to a library of loose pages and `.cbz`
archives, and keep them up to date unattended.

| File | Lines | What it is |
| --- | ---: | --- |
| `mirror_base.py` | ~640 | Scrapes one comic: the element-path lists, the arguments, the state a run keeps in module globals, and the loop - find the page's images, save them, press next. Everything it leans on is in `comiclib`, handed that state |
| `chapters.py` | ~190 | The command for everything about chapters; the work is in `comiclib/chapters/`, below |
| `web_ui.py` | ~20 | Where `update_comics` finds the web page's server; the server is in `comiclib/web/`, below |
| `web_ui.html` | ~1460 | The whole front end, one file, no build step |
| `update_comics.py` | ~190 | The long-running process: its arguments, the schedule loop, and starting the web page. The work is `comiclib` `config`, `library`, `batch` and `schedule` |
| `adopt_comic.py` | ~120 | Takes a folder of pages someone else scraped and makes it a comic this tool can update. The work is `comiclib/adopt/`: `scan`, `report`, `adopting` |
| `comiclib/` | ~760 | What more than one script needs to agree on, below |

`comiclib` is where anything two scripts both need goes, so the answer cannot drift between them:

| Module | What it is |
| --- | --- |
| `paths` | The config folder, the element-path file, and the one rule naming a comic's index file |
| `pages` | What makes two filenames one page (`page_key`), a page's number, reading order, the name a scrape gives an image |
| `metadata` | Reading and writing `mirror_metadata.json` (always written aside and moved into place), timestamps, settings to command and back, schema 1 to 2 |
| `cbz` | Every archive any script writes: a new one, one added to, a chapter's, a repack. The Uncompressed/CBZs shelf rule |
| `standin` | Draws a page for a page no reader can show. `cbz` asks it about every file, so every archive agrees |
| `exits` | `mirror_base`'s exit codes and what each means, and `MirrorError`, which carries one |
| `browser` | Starting the browser a scrape drives, and closing it however it ended |
| `elements` | Finding the comic image and the next link by element path, and pressing the link |
| `pagecheck` | `--check`: which known paths match a page, and what to add when none do |
| `download` | Fetching an image, with retries |
| `guards` | The checks before a page is written: running backwards, writing over another page, one page under two names |
| `runrecord` | What a scrape writes into the metadata about itself: settings, where it is up to, the run record |
| `walk` | `--index`: following a comic saving nothing, with the scrape's own image-finding and next |
| `config` | `ComicScraper.json`: the setup's settings and their defaults, read fresh before every run |
| `library` | `Comic`, finding every comic in a library, and the command each resumes with |
| `batch` | One update of a library: each comic its own process, the lock, chapters packed after, the summary |
| `schedule` | The daily time, and the `update-now` file that starts a run sooner |
| `web/` | The web page's server: the one job queue (`jobs`), what the page is shown (`views`), the element paths as it edits them (`elementpaths`), the add form (`adding`), the changes it can make (`edits`), and the http handler (`server`). The page itself is `web_ui.html`, at the top |
| `chapters/` | Walking a comic to record which page is which, and `KeptIndex`, the index a scrape adds to as it goes (`index`), lining that up against the files (`align`), reading an archive page (`archive_page`) or the addresses (`addresses`) for chapters, the chapter list and its corrections (`chapterlist`), packing per chapter (`packing`), and renumbering, inserting and refetching pages (`pageops`) |

The scripts import what they use by its old name (`chapters.page_key`, `mirror_base.metadata_file`), so
code reaching into a script still finds it; new code should import from `comiclib`.

Dependencies are **selenium and requests only**, on purpose (`requirements.txt`). Adding one means
rebuilding the container, which is a real cost to the person running this — `comiclib/standin.py` draws PNGs
with `zlib` and `struct` rather than take a dependency on Pillow. Assume the same constraint for
anything new.

## How the pieces fit

- **The repo sits inside a working comic library**, which is why `.gitignore` is an **allowlist**: `*`
  first, then `!name` for each tracked file. **A new file is untracked until it is named there.**
  `standin.py` was imported by two modules while committed nowhere, because of exactly this. Any change
  that adds a file must update `.gitignore` in the same commit. A folder needs two lines, `!folder/`
  then `!folder/*.py`, because `*` matches at every depth.
- **The library** holds `Uncompressed/<Comic>` for loose pages and `CBZs/` for archives. A comic's
  `output` and `cbz_path` are stored relative to the library root, so the library can move.
- **The scripts also run in a container**, from a folder mounted over the copies baked into the image
  (see the README's "Changing the scripts without rebuilding"). So **committing is not deploying**:
  the running copy is the mounted folder, and a new module has to reach it too or both scripts fail on
  import - `comiclib/` above all, which every script imports. `mirror_base.py`, `chapters.py`,
  `adopt_comic.py` and `web_ui.html` take effect immediately; `update_comics.py`, `web_ui.py` and
  anything in `comiclib/` need the container restarting, since the long-running process has them
  imported already (a scrape it starts imports `comiclib` afresh, but the web page does not).
- **Settings live in `config/` beside the scripts** — `ComicScraper.json`, `element_paths.json`, and
  `index/` (the per-comic record of which page is which). `MIRROR_CONFIG` overrides the folder,
  `MIRROR_ELEMENTS` the element-path file. That folder is the user's own data: **never edit or delete
  anything in it.**
- **The library is usually on a network share.** Listing a comic folder of a few thousand files takes
  minutes. Prefer one listing the user can provide over repeated directory reads, and expect file-heavy
  commands to need long timeouts.

## The ideas the code is built on

- **`mirror_metadata.json` in each comic folder is the single source of truth.** Its `settings` block is
  the only thing anyone edits; the scrape command is rebuilt from it every run (`settings_to_argv` in
  `update_comics.py`). Schema 2. `state` and `history` are what the tools have learned and done.
- **`ended` is the reader's judgement, never the scraper's.** A scrape can only know it has caught up
  with the latest page. Nothing in the code sets it; it comes from the report column, the web page's
  tick box, or a hand edit, and is carried through untouched. `state.completed` is a different thing:
  that *run* reached the latest page.
- **The index (`config/index/<comic>.<tag>.jsonl`) is one line per page, in reading order**, recording
  the address and the image. Position is meaning: line 1 is page 1. It can only be appended to from a
  context that knows its own offset — a scrape resuming mid-comic must not start one.
- **Alignment** matches that record against the files on disk, by name, by size, then by order. It has
  to *settle* before a comic can be chaptered. Missing pages are tolerated; unplaced files are not.
- **Element paths** are XPaths for the comic image and the next link, tried in order, with the winner
  remembered per comic. A library adds its own through `config/element_paths.json`, which is the
  sanctioned way to handle an awkward site — **do not special-case a comic in the code.**

## Conventions worth matching

- Comments explain **why**, in lower case, in prose, describing the kind of site that forced the
  behaviour ("a comic can re-serve an old page's image under a later page"). They are not narration of
  what the line does. Match the surrounding density; it is high.
- **No real webcomic is named anywhere in the repo** - not in code, comments, help text, the web page,
  the tests or the docs. Describe the shape of the site instead, and use `example.com` addresses and
  names like `MyComic` or `SomeAuthor/TheirComic`. The shipped element paths are the generic set from
  AChillVamp's original; the ones added for particular comics live in the user's own
  `config/element_paths.json`, which is where any new site-specific path belongs. AChillVamp's credit
  (`NOTICE`, the README, the header of `mirror_base.py`) is attribution, not a comic, and stays.
- Errors say what to do next, not just what failed ("Run this comic with `--prefix` so each page is
  numbered as it is saved").
- Flags that default on use `argparse.BooleanOptionalAction`, so `--no-thing` turns them off, and only
  the *off* case is written into a comic's settings.
- Files are written aside (`.writing`, `.packing`) and moved into place, so an interrupted run leaves
  nothing half-written.
- Exit codes from `mirror_base.py` mean something and are checked by callers:
  `0` ok, `1` interrupted, `2` usage, `3` no image found, `4` download failed, `5` driver,
  `6` timeout, `7` unexpected, `8` next link runs backwards, `9` the site reuses filenames.

## Testing

The suite is `tests/`, run with pytest (`pip install -r requirements-dev.txt`, which the container never
needs). `python -m pytest` runs all of it side by side (`pytest.ini` asks xdist for up to 16 workers) in
under a minute; `-m "not browser"` runs the offline half in seconds, and `-n 0` runs one test at a time
for reading its output. Tests that need Chrome skip themselves on a machine without it.

Browser tests wait for what they are waiting for - `wait_until`, `open_page`, `checked` in the harness -
never a fixed sleep: a pause long enough for the slowest machine was most of what the suite used to spend.

`tests/conftest.py` is the harness: a fake comic served on a local port, a stalling server, a library
and config folder of each test's own under `tmp_path` (named through `MIRROR_CONFIG`, so every script a
test starts reads that and not the real one), the web page started over it, and fixtures that import
`mirror_base` and `chapters` afresh - `mirror_base` keeps its run in module globals and reads its
element paths on import, so a plain import would carry one test into the next.

Nothing in the suite reaches the internet or a real library, and nothing names a real comic: a behaviour
a real site forced is reproduced with a made-up one of the same shape. Run it before and after changing
shared behaviour; it passes in full at `HEAD`, so a failure is yours.

## Things that have bitten, more than once

- **A feature landing in the wrong layer.** A comic with one archive and a comic with one per chapter
  need the same answer to "what does a reader see here". Twice now something went into `chapters.py`
  or the aligner and had to be pulled out for `mirror_base` to use it.
- **Presence standing in for completeness.** The web page asked whether an index file *existed* and
  took a one-line stub to mean a walked comic. Ask what something holds, not whether it is there.
- **A rule that is 99.9% right.** A comic can re-serve an old page's image under a new page, so "name
  the file after the site's image" would have overwritten a page 1,500 earlier. On a library of
  thousands of files, check the exception before a rename or a delete.
- **Heredocs.** Do not edit files by piping a script into `python - <<'EOF'`; backslashes are mangled
  before the shell sees them and the failure is silent. Use the editor tools.
