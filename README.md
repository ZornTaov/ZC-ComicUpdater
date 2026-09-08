# Comic Mirror

Downloads a webcomic page by page, packs it into a `.cbz`, and remembers enough about the run to
carry on from where it stopped the next time. Point it at a library folder and it will update every
comic in it unattended, on a timer, in a container if you like.

The problem it solves is not the first download — it is the fifth year of updates. A comic you have
been following for a decade is a 250 MB archive, and adding this week's three pages should not mean
rewriting or re-syncing 250 MB.

## The three scripts

| Script | What it does |
| --- | --- |
| `mirror_base.py` | Scrapes one comic, saves the pages, appends them to its `.cbz`, writes its metadata. |
| `update_comics.py` | Walks a library, resumes every comic from its metadata, on demand or on a schedule. |
| `adopt_comic.py` | Writes metadata for comics you already have, so they join the rotation without re-downloading. |

## Requirements

- Python 3.8 or newer
- Chrome or Firefox installed (Selenium 4.6+ fetches the matching driver by itself)

```sh
pip install -r requirements.txt
```

Or skip all of that and use the container — see [Running in Docker](#running-in-docker).

## Quick start

Grab one comic:

```sh
python mirror_base.py --output "Uncompressed/MyComic" "https://example.com/comic/first-page/"
```

It works out where the page image and the "next" link are, walks forward until there is no next page,
saves each image, and writes `Uncompressed/MyComic.cbz` plus a `mirror_metadata.json` inside the
folder. Run the same command again later and it starts from the page it stopped on, adding only what
is new to the archive.

Useful flags:

```sh
-p, --prefix            number the saved files, instead of keeping the site's filenames
-i, --increment N       what number to count from (with -p)
-o, --output PATH       where the pages go
    --cbz-path PATH     where the .cbz goes, if not the default
    --no-cbz            save pages only, no archive
    --no-headless       show the browser window, for working out why a site misbehaves
-v, --verbose           log every step
```

`--prefix` matters more than it looks. Many comics change their filename scheme partway through
their run — a date stamp becomes `NAME_0421.jpg` — and once that happens the files no longer sort
into reading order. A prefix pins the order to the order you downloaded them in, which is the order
the comic was published in.

## Library layout

`update_comics.py` finds comics by looking for `mirror_metadata.json`, so it does not care how you
arrange things. The layout the tools assume by default is:

```
Comics/
  CBZs/                     what your reader points at
    MyComic.cbz
    SomeAuthor/
      TheirComic.cbz
  Uncompressed/             the loose pages the scraper works against
    MyComic/
      0001_page.jpg
      mirror_metadata.json
    SomeAuthor/
      TheirComic/
```

Keeping the archives in their own tree matters if you read over SMB — Perfect Viewer and readers like
it will happily try to index every folder of loose pages as its own comic otherwise. It also means a
`rsync` to a phone or a Chromebook can pull `CBZs/` alone.

When `--cbz-path` is not given, `mirror_base.py` picks the archive in this order:

1. an archive already sitting beside the output folder, so nothing that exists is ever orphaned
2. the mirror of the folder's path under a sibling `CBZs/` tree — `Uncompressed/A/B` becomes `CBZs/A/B.cbz`
3. failing both, beside the folder

Comics may be nested a few folders deep, grouped by author or site; `--max-depth` sets how far down
the updater looks (5 by default).

## Adopting comics you already have

If you already have a pile of comics, `adopt_comic.py` writes metadata for them so they join the
rotation instead of being downloaded again. For a whole library, the sensible route is a spreadsheet.

**1. Scan and write a report:**

```sh
python adopt_comic.py --scan --root "D:/Comics" --report comics.csv
```

Every folder or `.cbz` that holds pages but has no metadata becomes a row, with the page count and
numbering scheme filled in.

**2. Fill in the columns only you know** — see `comics.example.csv`:

| Column | Meaning |
| --- | --- |
| `last_url` | Address of the last page you have. The next run re-saves it and carries on. |
| `next_url` | Use instead of `last_url` when re-saving that page would make a differently named duplicate. |
| `ended` | `TRUE` for a finished comic. No address needed, and it is skipped from then on. |
| `increment` | The last page's number, for comics you number yourself. |
| `prefix` | `TRUE` to keep numbering new pages. Implies `increment`. |
| `cbz_path` | The archive this comic belongs to, if it is not beside the folder. |

Leave `prefix` and `increment` blank and the comic keeps whatever filenames the site hands out, which
is right for sites that already number their pages sensibly.

**3. Read it back:**

```sh
python adopt_comic.py --read-report comics.csv --root "D:/Comics"
```

Rows with no address and no `ended` mark are left alone, so you can fill the sheet in over several
sittings. Re-running `--report` preserves everything you have already typed, matching rows up again
even if you have since moved folders around.

Single comics can be done directly:

```sh
python adopt_comic.py "Uncompressed/MyComic" --root "D:/Comics" \
    --last-url "https://example.com/comic/412" --increment 412 --prefix \
    --cbz-path "CBZs/MyComic.cbz" --dry-run
```

A comic that exists only as a `.cbz` works too — make the folder, leave it empty, and pass
`--cbz-path`. The page count and numbering are read out of the archive, and the folder fills up as
new pages arrive.

## Running unattended

```sh
python update_comics.py "D:/Comics" --dry-run     # what would run, and with what arguments
python update_comics.py "D:/Comics"               # run once
python update_comics.py "D:/Comics" --schedule 03:30 --jobs 2
```

Each comic is a separate process, so one badly behaved site cannot take the run down with it.
`--timeout` (30 minutes by default) kills anything that hangs, along with the whole browser process
tree it started. Comics marked as ended are skipped. `--only NAME` limits the run to one comic, and
may be repeated.

`--schedule HH:MM` keeps the process alive and starts an update at that local time daily. It prints
the wall clock and time zone it believes it is in when it starts, because getting that wrong is the
easiest way to have updates fire twelve hours from where you wanted them.

An updater run summarises what each comic did, including the exit code from `mirror_base.py`:

| Code | Meaning |
| --- | --- |
| 0 | finished normally |
| 1 | interrupted |
| 2 | bad arguments |
| 3 | no image found on the page — usually a site redesign |
| 4 | a download failed after retries |
| 5 | the browser or driver would not start |

Code 3 on a comic that used to work is the one to look at: the site has changed its markup and the
saved XPath no longer matches.

## Running in Docker

The image pins Chromium and a matching ChromeDriver together, so a host update cannot break the pair.

```sh
docker compose build
docker compose up -d
docker compose logs -f
```

Edit `docker-compose.yml` before the first run:

- `volumes` — point it at your library, mounted as `/library`
- `TZ` — **required**, or the container runs on UTC and the schedule fires at the wrong hour
- `user` — set it to the owner of the library folder (`ls -n` shows the numbers), so scraped pages
  land readable to whatever shares them rather than owned by root
- `command` — the schedule and how many comics to update at once

This runs happily on a NAS. On QNAP Container Station, memory limits belong in Advanced Settings
rather than `mem_limit` in the compose file, which Container Station rejects. If `docker build` fails
with a permission error about a home directory, run it as `HOME=/tmp DOCKER_CONFIG=/tmp/.docker docker build ...`.

Three environment variables override browser discovery, which is how the container points Selenium at
its bundled Chromium. They are deliberately not command line flags, so they never end up baked into a
comic's saved resume command:

- `MIRROR_BROWSER_BINARY`
- `MIRROR_DRIVER_BINARY`
- `MIRROR_BROWSER_ARGS`

## How the archives stay cheap to sync

A zip file stores its entries in the order they were written and keeps its index at the end. Adding
pages therefore means writing the new entries after the existing bytes and rewriting only that index —
every byte already in the file stays exactly where it was.

That is not a micro-optimisation. On a real 250 MB archive, adding a fortnight of pages left
**97.8% of the file byte-identical** and took a tenth of a second. Anything doing block-level delta
transfer — `rsync`, Syncthing — carries the new pages and nothing else. It also keeps copy-on-write
snapshots on ZFS or btrfs from growing by a whole archive every time a comic updates.

Pages are stored, not deflated: they are already-compressed JPEG and PNG, so compressing them again
costs CPU to save nothing.

## The metadata file

`mirror_metadata.json` sits in each comic's folder and is packed into its archive. It holds the
resume URL and page number, the XPaths that worked for that site, the exact arguments needed to
continue, and a capped history of past runs. It is plain JSON and safe to edit by hand.

Because the file is what marks a folder as a comic, moving a comic within the library is enough —
the updater notices the folder no longer matches the saved `--output` and corrects it, rather than
believing stale metadata and scraping a fresh copy somewhere else.

## Notes and limits

- Sites that need a login, or that paginate with JavaScript only, will not work as-is. `-ej` enables
  JavaScript in the driver, which is off by default because pages load faster without it.
- The image and "next" element are found by trying a list of common XPaths. The one that works is
  remembered per comic. If a comic's newest page has different markup to every page before it — which
  happens, since many themes wrap the image in a link to the next page and the newest page has no next
  page — the search runs again rather than giving up.
- `-m` and `-n` let you supply the XPaths yourself for a site the guesses do not cover.
- Be considerate: this drives a real browser against someone's site. `-w` sets a wait between pages.

## Credits

`mirror_base.py` was originally written by AChillVamp.
