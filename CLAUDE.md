# Working on this project

Notes for whoever picks this up next, written down because they were worked out the slow way more than
once. The project is **ZornCoMix** - ZornCoMix Updater and ZornCoMix Reader, `zcm-` for short in image and
container names; it was ZC-ComicUpdater before, and archives already made still say so in their ComicInfo
notes, which are left alone since a changed note would rewrite every archive's ComicInfo. The user-facing
documentation is the GitHub wiki (https://github.com/ZornTaov/ZornCoMix/wiki, its own git repo,
`ZornCoMix.wiki.git`) - read it for *what* the tools do; the README is a short front page pointing there. A change users would notice needs its wiki page updated too.
This file is about *how the pieces fit* and *what is easy to get wrong*.

Paths on any particular machine — which drive the library is on, where the container folder is mounted —
are deliberately **not** in this file, since it is tracked. They belong in local notes.

## What this is

Six scripts, and the package they share, that mirror webcomics to a library of loose pages and `.cbz`
archives, and keep them up to date unattended.

| File | Lines | What it is |
| --- | ---: | --- |
| `mirror_base.py` | ~640 | Scrapes one comic: the element-path lists, the arguments, the state a run keeps in module globals, and the loop - find the page's images, save them, press next. Everything it leans on is in `comiclib`, handed that state |
| `chapters.py` | ~190 | The command for everything about chapters; the work is in `comiclib/chapters/`, below |
| `web_ui.py` | ~20 | Where `update_comics` finds the web page's server; the server is in `comiclib/web/`, below |
| `web_page/` | ~1500 | The whole front end, no build step: `index.html`, `css/`, and `js/` with one plain script per part of the page. See "The web page" below |
| `update_comics.py` | ~190 | The long-running process: its arguments, the schedule loop, and starting the web page. The work is `comiclib` `config`, `library`, `batch` and `schedule` |
| `adopt_comic.py` | ~120 | Takes a folder of pages someone else scraped and makes it a comic this tool can update. The work is `comiclib/adopt/`: `scan`, `report`, `adopting` |
| `run_plugin.py` | ~130 | Runs a comic another program scrapes, through its plugin in `config/plugins/`; `--add` starts one, `--list` shows the plugins, `--install`/`--update` fetch one from its repository. The work is `comiclib` `plugins`, `intake`, `pluginrun`, `pluginenv`, `pluginfetch`. See "Scraper plugins" below |
| `examples/plugins/example/` | ~200 | The example plugin: a template for writing one, and what the suite runs. Its `tool/` draws a made-up series |
| `comiclib/` | ~760 | What more than one script needs to agree on, below |
| `reader/` | ~1500 | A separate program: a PerfectViewer-style web reader for the library, in its own image. See "The reader" below |

`comiclib` is where anything two scripts both need goes, so the answer cannot drift between them:

| Module | What it is |
| --- | --- |
| `paths` | The config folder, the element-path file, and the one rule naming a comic's index file |
| `pages` | What makes two filenames one page (`page_key`), a page's number, reading order, the name a scrape gives an image |
| `metadata` | Reading and writing `mirror_metadata.json` (always written aside and moved into place), timestamps, settings to command and back, schema 1 to 2 |
| `cbz` | Every archive any script writes: a new one, one added to, a chapter's, a repack. The Uncompressed/CBZs shelf rule |
| `standin` | Draws a page for a page no reader can show. `cbz` asks it about every file, so every archive agrees |
| `comicinfo` | The `ComicInfo.xml` every archive carries (v2.1 draft, in the schema's element order), and a picture's size read from its first bytes. `cbz` writes it last-but-metadata and an append rewrites both on the end. Another program's ComicInfo is kept (`kept_tags`, in the metadata as `comicinfo` or a chapter's `comicinfo`) and written back: typed by hand beats it, it beats what is worked out here, and its `Pages`/`PageCount`/`Count` are never believed. `build` must give the same bytes for the same input - that is how an archive is known to be current |
| `plugins` | Finding a plugin, checking its `plugin.json` and a comic's settings against its fields, building its command, a plugin comic's first metadata |
| `intake` | Taking in what a plugin's program wrote: pages numbered on, a chapter's name in each of its pages' names (or every chapter's `001.jpg` is one `page_key`), nothing written over, the same file fetched again not taken twice, chapters added to the list |
| `pluginrun` | One plugin run: leftovers of a killed run taken in, the program run in the staging folder until its deadline, the run recorded, the single archive kept |
| `pluginenv` | A plugin's python packages (`install` in its `plugin.json`), in a `.venv` of its own in its folder, built again when its stamp says another python or another ask; and the programs it `needs`, only looked for |
| `pluginfetch` | Installing a plugin from its git repository (cloned aside, checked, renamed to its `id`), updating it, removing one no comic uses, and whether the web page may (`MIRROR_WEB_PASSWORD`, or `MIRROR_ALLOW_PLUGIN_INSTALLS`) |
| `exits` | `mirror_base`'s exit codes and what each means, and `MirrorError`, which carries one |
| `browser` | Starting the browser a scrape drives, and closing it however it ended |
| `elements` | The element paths shipped as examples (comic image, next link, first-page link), finding the image and the links by them, and pressing a link |
| `pagecheck` | `--check`: which known paths match a page, and what to add when none do |
| `download` | Fetching an image, with retries |
| `guards` | The checks before a page is written: running backwards, writing over another page, one page under two names |
| `runrecord` | What a scrape writes into the metadata about itself: settings, where it is up to, the run record |
| `walk` | `--index`: following a comic saving nothing, with the scrape's own image-finding and next |
| `config` | `ComicScraper.json`: the setup's settings and their defaults, read fresh before every run |
| `library` | `Comic`, finding every comic in a library, and the command each resumes with |
| `batch` | One update of a library: each comic its own process, the lock, chapters packed after, the summary |
| `runlogs` | Everything a comic says during an update, a file per run in `logs/` beside the config folder (`MIRROR_LOGS` overrides), kept a week. Its pipe is read as bytes and split here, since a progress bar redrawn with `\r` is kept once, as last drawn, and shown on the page as it is drawn |
| `schedule` | The daily time, and the `update-now` file that starts a run sooner |
| `moving` | Moving a comic to another folder of the library: its pages, its archive or chapter archives to the matching place on the CBZs shelf, the settings naming them, and its index named in the comic so it is still found. Renames only, undone if one fails. Each rename goes into `history.moves`, which the reader reads (through `metadata.moves`/`before_moves`) to carry a comic's place, settings and cover to its new id - so a scrape must keep that key, as `runrecord` does |
| `web/` | The web page's server: the one job queue (`jobs`), what the page is shown (`views`), the element paths as it edits them (`elementpaths`), the add form (`adding`), a comic uploaded as a zip and put in or adopted (`uploads`), the changes it can make (`edits`), and the http handler (`server`). The page itself is `web_page/`, at the top |
| `chapters/` | Walking a comic to record which page is which, and `KeptIndex`, the index a scrape adds to as it goes (`index`), the same index read from a WordPress site's post list instead of walked (`wordpress`), lining that up against the files (`align`), reading an archive page (`archive_page`) or the addresses (`addresses`) for chapters, the chapter list and its corrections (`chapterlist`), a chapter's own number read from its label (`numbering`), packing per chapter (`packing`), and renumbering, inserting and refetching pages (`pageops`) |

The scripts import what they use by its old name (`chapters.page_key`, `mirror_base.metadata_file`), so
code reaching into a script still finds it; new code should import from `comiclib`.

### The web page

`web_page/` is the page, served file by file by `comiclib/web/server.py`, which hands out only the
`.html`, `.css` and `.js` inside that folder. `index.html` is the markup, every section and dialog;
`css/` is `base` (colours and controls), `page` (the sections), `dialogs`, and `elements` (the element
paths dialog and the check result). `js/` holds one file per part of the page: `common` (`$`, `api`,
`post`, `esc`, the time formats), `library`, `running` (the `/api/state` poll: Running now, queue, Recent,
log), `editor`, `elements`, `listcheck`, `bounds`, `adding`, `uploads`, `settings`, `plugins` (a plugin's
settings as a form), and `main`, which starts it all.

They are **plain scripts sharing one global scope, not modules**, on purpose: the dialogs hand each other
state (`editing`, `checkJob`, `paths`), and an imported `let` cannot be assigned to. So a top-level name
must be declared in exactly one file, and **only `main.js` may call anything as it loads**, since a
script can then use what a later one declares. The one exception is a plugin's own `dialog.js`, served from
`/plugins/<name>/` and loaded on demand long after `main.js` has run, which registers itself in `pluginForms`
as it loads. A part of the page only the built-in scraper has is marked `builtin-only`, and one only a
plugin comic has `plugin-only`; a `with-plugin` class on the add section or the editor picks which shows. `index.html` loads them in order, `main.js` last. A new
file needs a `<script>` tag there, and a new folder needs its two lines in `.gitignore`.
`tests/test_web_status.py` runs the Result column's expression out of `js/library.js` by text, so moving
that expression means moving the test's markers with it.

### The reader

`reader/` is its own program with its own image, dependencies and tests, sharing only `comiclib` -
imported, never copied, so it cannot disagree with the scraper about which page comes next.
`comicreader/` is a FastAPI server (`sources`: an archive or loose folder as a page list, kept from its
last good reading while the scraper appends to it; `library`: every comic as one stream of pages across
its chapter archives, and where the reader is up to by `page_key`, not by number; `store`: sqlite in its
data folder; `app`: the routes). `web/` is TypeScript built by Vite inside the image (the scraper's
`web_page/` stays build-free); the arithmetic - spreads, taps, keys, shelves - is in `layout.ts` and
`shelves.ts` so Vitest can test it without a browser. It mounts the library **read-only**.

Its suite runs apart: `cd reader && python -m pytest` (offline, a couple of seconds; `reader/pytest.ini`
makes it its own root) and `npm test` in `reader/web`. `tests/test_contract.py` there checks what it
relies on comiclib for, so **run it after any comiclib change**. Build with
`docker build -f reader/Dockerfile -t zcm-reader:local .` from the repo root.

### Scraper plugins

A comic another program scrapes has `settings.scraper` (the plugin's folder name in `config/plugins/`) and
`settings.plugin` (its settings; its address is `settings.url`, as every comic's is). `library.resume_argv`
gives `run_plugin.py` just the comic, `batch.program` picks that over `mirror_base` and gives it a
`--deadline` a little inside the batch's timeout - killed by the timeout instead, a long catch-up would be
thrown away every day. The program runs in `<comic>/.plugin-staging/` and what it wrote is taken in after;
a run killed part way leaves it there, and the next run takes in whatever of it is whole first. On Linux
the program shares `run_plugin`'s process group, so the batch's `killpg` takes it too.

Each plugin is the user's own, in its own repository, the program itself usually a submodule in its
`tool/`. Its `plugin.json`'s `id` names its folder - and so every comic's `settings.scraper` - and a folder
of another name is refused rather than guessed at. The web page's Plugins dialog (and `run_plugin.py
--install`/`--update`) clones it with git, which the image carries for this. Its python packages go in
`<plugin>/.venv`, made `--system-site-packages` so the image's selenium is still seen: the config mount
keeps it through a new image, and a stamp written last rebuilds it when the image's python changes. The
plugin's command runs with that venv's python - `{python}`, or a `plugin.py` command starting with
`sys.executable`, which is swapped for it. Nothing apt would install is handled yet, only named in `needs`
and reported missing; that waits for a plugin that needs one. Nothing of a real plugin - nor the site it is for - is named in this repo; `examples/` holds the
generic one. A plugin's `plugin.py` runs only in the process running its comic; the web page reads only its
`plugin.json`. A plugin comic's chapters have `source: "plugin"`: never walked or aligned, packed by its
pages' numbers (`numbered_pages`), the way a comic cut `every` so many pages is.

Dependencies are **selenium and requests** today (`requirements.txt`). Adding one is allowed when it is
genuinely needed, but it means rebuilding the container, which is a real cost to the person running this -
so **say plainly whether a change needs a rebuild, a restart, or neither**. Prefer the standard library
where it is cheap to (`standin.py` draws PNGs and `comicinfo.py` reads image sizes with `zlib` and
`struct`), and keep `comiclib`'s archive and page modules stdlib-only, since other programs import them.

## How the pieces fit

- **The repo sits inside a working comic library**, which is why `.gitignore` is an **allowlist**: `*`
  first, then `!name` for each tracked file. **A new file is untracked until it is named there.**
  `standin.py` was imported by two modules while committed nowhere, because of exactly this. Any change
  that adds a file must update `.gitignore` in the same commit. A folder needs two lines, `!folder/`
  then `!folder/*.py`, because `*` matches at every depth.
- **The library** holds `Uncompressed/<Comic>` for loose pages and `CBZs/` for archives. A comic's
  `output` and `cbz_path` are stored relative to the library root, so the library can move.
- **The scripts also run in a container**, from a folder mounted over the copies baked into the image
  (see the wiki's Docker page, "Changing the scripts without rebuilding"). So **committing is not deploying**:
  the running copy is the mounted folder, and a new module has to reach it too or both scripts fail on
  import - `comiclib/` above all, which every script imports. `mirror_base.py`, `chapters.py`,
  `adopt_comic.py`, `run_plugin.py` and `web_page/` take effect immediately; `update_comics.py`, `web_ui.py` and
  anything in `comiclib/` need the container restarting, since the long-running process has them
  imported already (a scrape it starts imports `comiclib` afresh, but the web page does not).
- **A version tag publishes both images; a push to main does not.** `.github/workflows/images.yml` builds
  the updater and the reader for amd64 and arm64 and pushes them to `ghcr.io/zorntaov/` as `zcm-updater`
  and `zcm-reader`, and under their names from before the rename (`comics-updater`, `comic-reader`) too,
  until a release drops those (each matrix entry's `legacy`). The two share one
  version: `git tag v1.2.0 && git push origin v1.2.0` releases both as `:1.2.0`, `:1.2`, `:1` and
  `:latest`, which both compose files pull. Main is built as `:nightly` (and `:sha-<commit>`) once a night,
  only when it has moved. A release reaches whoever next pulls - not a container running already, nor one
  running scripts from a mounted folder. Tag a release only when the user asks for one.
- **Settings live in `config/` beside the scripts** — `ComicScraper.json`, `element_paths.json`,
  `index/` (the per-comic record of which page is which), and `plugins/` (each scraper plugin). `MIRROR_CONFIG` overrides the folder,
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
  with the latest page. It comes from the report column, the web page's tick box, or a hand edit, and is
  carried through untouched. The one exception is a plugin whose site says a series is finished: its
  `plugin.py` `ended()` returning `True`, after a run whose program finished, marks the comic ended
  **once** (`history.plugin_ended` records it, in `pluginrun.may_mark_ended`), so a comic the person
  unticks is never marked again. `state.completed` is a different thing: that *run* reached the latest page.
- **The index (`config/index/<comic>.<tag>.jsonl`) is one line per page, in reading order**, recording
  the address and the image. Position is meaning: line 1 is page 1. It can only be appended to from a
  context that knows its own offset — a scrape resuming mid-comic must not start one.
- **A chapter has two numbers.** `chapters.list[].number` is its *place* in the comic (1..n, set by
  `settle_chapters`), which fixes, messages and the list itself go by. Its *own* number, `called`, is read
  from its label by `comiclib/chapters/numbering.py` (`Chapter 391`, `Book #12`, an intermission after 12 is
  12.5), **worked out every time and never stored**, and falls back to the place for a comic whose labels do
  not number it in order. The archive name (`c391`, `c012.5`) and ComicInfo `Number` use `called`, and the
  reader imports the same module to match an archive to its chapter. Packing renames an archive still
  named by its place - only that exact old name - and records the rename in `history.moves` with a
  `pages` step for the comic's own folder, since the reader keeps a chapter by its archive's path.
- **Alignment** matches that record against the files on disk, by name, by size, then by order. It has
  to *settle* before a comic can be chaptered. Missing pages are tolerated; unplaced files are not.
- **Element paths** are XPaths for the comic image and the next link, tried in order, with the winner
  remembered per comic, and for the first-page link a walk follows back to page 1 when a comic's start
  was never recorded - a walk that finds none stops, rather than start an index part way through. A library adds its own through `config/element_paths.json`, which is the
  sanctioned way to handle an awkward site — **do not special-case a comic in the code.**

## Conventions worth matching

- Comments explain **why**, in lower case, in prose, describing the kind of site that forced the
  behaviour ("a comic can re-serve an old page's image under a later page"). They are not narration of
  what the line does. Match the surrounding density; it is high.
- **No real webcomic is named anywhere in the repo** - not in code, comments, help text, the web page,
  the tests or the docs. Describe the shape of the site instead, and use `example.com` addresses and
  names like `MyComic` or `SomeAuthor/TheirComic`. The shipped element paths are a short generic set,
  one per common kind of site (WordPress comic themes, ComicControl, `rel="next"`), kept in
  `comiclib/elements.py` as `shipped`, in the same `{xpath, note}` shape as `element_paths.json`. They
  are examples as much as defaults; the ones added for particular comics live in the user's own
  `config/element_paths.json`, which is where any new site-specific path belongs. Naming comic
  *software* is fine; naming a comic is not. AChillVamp's credit (`NOTICE`, the README, the header of
  `mirror_base.py`) is attribution, not a comic, and stays.
- **The license is PolyForm Noncommercial 1.0.0** (`LICENSE`, verbatim - never edit it; the copyright
  line lives in `NOTICE` as its `Required Notice:`). No dependency or copied code may carry terms that
  conflict with that.
- Errors say what to do next, not just what failed ("Run this comic with `--prefix` so each page is
  numbered as it is saved").
- Flags that default on use `argparse.BooleanOptionalAction`, so `--no-thing` turns them off, and only
  the *off* case is written into a comic's settings.
- Files are written aside (`.writing`, `.packing`) and moved into place, so an interrupted run leaves
  nothing half-written.
- Exit codes from `mirror_base.py` mean something and are checked by callers:
  `0` ok, `1` interrupted, `2` usage, `3` no image found, `4` download failed, `5` driver,
  `6` timeout, `7` unexpected, `8` next link runs backwards, `9` the site reuses filenames,
  `10` next link skips pages the comic's index lists, `11` the same picture found as the comic on page after
  page; and `run_plugin.py`'s own, `12` the plugin's program failed, `13` it ran out of time (what it got is kept).

## Testing

The suite is `tests/`, run with pytest (`pip install -r requirements-dev.txt`, which the container never
needs). `python -m pytest` runs all of it side by side (`pytest.ini` asks xdist for up to 16 workers), at
below-normal priority that every browser and script it starts inherits (`run_politely` in `conftest.py`),
with every Chrome reusing a profile from a pool (`share_profiles`, `MIRROR_PROFILE_POOL`) rather than making
one. `-m "not browser"` runs the offline half in seconds, and `-n 0` runs one test at a time for reading its
output. A run is felt on the rest of the machine at any worker count - a video beside it hitched at 4 as at
16 - so it runs fast and is over sooner; the pool and the priority keep it as light as it can be. Tests that need Chrome skip themselves on a machine without it.

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
