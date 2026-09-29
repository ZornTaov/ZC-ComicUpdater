# Working on this project

Notes for whoever picks this up next, written down because they were worked out the slow way more than
once. The README is the user-facing documentation and is thorough — read it for *what* the tools do.
This file is about *how the pieces fit* and *what is easy to get wrong*.

Paths on any particular machine — which drive the library is on, where the container folder is mounted —
are deliberately **not** in this file, since it is tracked. They belong in local notes.

## What this is

Five scripts (plus one shared module) that mirror webcomics to a library of loose pages and `.cbz`
archives, and keep them up to date unattended.

| File | Lines | What it is |
| --- | ---: | --- |
| `mirror_base.py` | ~1660 | Scrapes one comic: drives a browser, follows next links, downloads pages, writes the metadata, packs the single archive |
| `chapters.py` | ~2280 | Everything about chapters: walking a comic to record which page is which, lining that up against the files, reading an archive page, packing one archive per chapter |
| `web_ui.py` | ~1160 | The web page's server: a job runner and a JSON API over the library |
| `web_ui.html` | ~1460 | The whole front end, one file, no build step |
| `update_comics.py` | ~860 | Finds every comic in a library and updates them on a schedule; hosts the web page |
| `adopt_comic.py` | ~800 | Takes a folder of pages someone else scraped and makes it a comic this tool can update |
| `standin.py` | ~240 | Draws a page for a page no reader can show. Shared by `mirror_base` and `chapters` |

Dependencies are **selenium and requests only**, on purpose (`requirements.txt`). Adding one means
rebuilding the container, which is a real cost to the person running this — `standin.py` draws PNGs
with `zlib` and `struct` rather than take a dependency on Pillow. Assume the same constraint for
anything new.

## How the pieces fit

- **The repo sits inside a working comic library**, which is why `.gitignore` is an **allowlist**: `*`
  first, then `!name` for each tracked file. **A new file is untracked until it is named there.**
  `standin.py` was imported by two modules while committed nowhere, because of exactly this. Any change
  that adds a file must update `.gitignore` in the same commit.
- **The library** holds `Uncompressed/<Comic>` for loose pages and `CBZs/` for archives. A comic's
  `output` and `cbz_path` are stored relative to the library root, so the library can move.
- **The scripts also run in a container**, from a folder mounted over the copies baked into the image
  (see the README's "Changing the scripts without rebuilding"). So **committing is not deploying**:
  the running copy is the mounted folder, and a new module has to reach it too or both scripts fail on
  import. `mirror_base.py`, `chapters.py`, `adopt_comic.py`, `standin.py` and `web_ui.html` take effect
  immediately; `update_comics.py` and `web_ui.py` need the container restarting, being the long-running
  process.
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

- Comments explain **why**, in lower case, in prose, often naming the comic that forced the behaviour
  ("avasdemon.com serves page 2747 as 1273.png"). They are not narration of what the line does. Match
  the surrounding density; it is high.
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
needs). `python -m pytest tests` runs all of it in about eight minutes; `-m "not browser"` runs the
offline half in seconds. Tests that need Chrome skip themselves on a machine without it.

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
- **A rule that is 99.9% right.** Ava's Demon re-serves an old page's image (`2747` is `1273.png`), so
  "name the file after the site's image" would have overwritten a page 1,500 earlier. On a library of
  thousands of files, check the exception before a rename or a delete.
- **Heredocs.** Do not edit files by piping a script into `python - <<'EOF'`; backslashes are mangled
  before the shell sees them and the failure is silent. Use the editor tools.
