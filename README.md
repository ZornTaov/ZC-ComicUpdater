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
| `web_ui.py`, `web_ui.html` | The optional web page `update_comics.py --web` serves. |
| `config/ComicScraper.json` | Settings: where pages and archives go, and what a run defaults to. |
| `config/element_paths.json` | The XPaths every scrape tries, when the built-in ones are not enough. |
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
    --prime             save the first page, check the next link, then stop
    --keep-index        record which page is which as it saves, for chaptering later
```

`--prefix` matters more than it looks. Many comics change their filename scheme partway through
their run — a date stamp becomes `NAME_0421.jpg` — and once that happens the files no longer sort
into reading order. A prefix pins the order to the order you downloaded them in, which is the order
the comic was published in.

### Priming comics to download elsewhere

Scraping over a network share is slow, since every page is written across the network. `--prime`
saves only the first page, follows the next link once to prove it works, writes the metadata and
archive, and stops:

```sh
python mirror_base.py --prime -o "Q:/Comics/Uncompressed/MyComic" "https://example.com/comic/first-page/"
```

The metadata resumes on the second page, so the next `update_comics.py` run, on the machine that holds
the library, downloads the rest. If priming reports there is no next button, the comic either has one
page or needs its next element added before it is worth queueing.

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
python update_comics.py "D:/Comics" --schedule 03:30 --now   # and once immediately
```

`--now` updates once straight away and then settles into the schedule. Worth having on a container:
otherwise a fresh start does nothing at all until the small hours, which makes a working setup hard
to tell apart from a broken one.

Each comic is a separate process, so one badly behaved site cannot take the run down with it.
`--timeout` (30 minutes by default) kills anything that hangs, along with the whole browser process
tree it started. Comics marked as ended are skipped. `--only NAME` limits the run to one comic, and
may be repeated.

`--schedule HH:MM` keeps the process alive and starts an update at that local time daily. It prints
the wall clock and time zone it believes it is in when it starts, because getting that wrong is the
easiest way to have updates fire twelve hours from where you wanted them.

### Starting an update without waiting

While `--schedule` is waiting, it looks for a file named `update-now` (or `update-now.txt`) in the
library root every 30 seconds. When one appears it is deleted and an update starts straight away. An
empty file updates everything; otherwise list comic folders in it, one per line, to update only those:

```text
# lines starting with # are ignored
Uncompressed/Snafu-Comics/nsma
gg
Uncompressed/Snafu-Comics/*
```

Wildcards work, and `*` reaches into subfolders, so `Uncompressed/Snafu-Comics/*` is every comic under
that folder however deeply it is nested. The same patterns work with `--only`.

That is the whole interface to a running container: anything that can write to the library share can
start a run, with no SSH and no restart. Paired with `--prime`, adding a batch of new comics is: prime
them from your own machine, drop an `update-now.txt` naming them, and let the container do the bulk
download. Its progress shows in the container log as usual.

An updater run summarises what each comic did, including the exit code from `mirror_base.py`:

| Code | Meaning |
| --- | --- |
| 0 | finished normally |
| 1 | interrupted |
| 2 | bad arguments |
| 3 | no image found on the page — usually a site redesign |
| 4 | a download failed after retries |
| 5 | the browser or driver would not start |
| 6 | a page never finished loading |
| 7 | something unexpected, printed with the error |
| 8 | the next link is running backwards through pages already held |

Code 3 on a comic that used to work is the one to look at: the site has changed its markup and the
saved XPath no longer matches. Code 6 is usually transient and worth simply retrying.

A comic that stalls is reported as each comic finishes rather than in the order they started, so
one slow site no longer holds back the log lines for everything that overtook it.

## The web page

```sh
python update_comics.py "D:/Comics" --web 8080
python update_comics.py "D:/Comics" --schedule 03:30 --web 8080
```

Then open `http://localhost:8080/`, or the NAS's address from anywhere on your network. The page
shows:

- **Running now**: every comic in the current job, the pages it has gained so far, how long it has
  been going, and the last line its scraper printed. **Stop** kills the job; pages already saved are
  kept, and the metadata resumes from where it stopped.
- **Queued**: jobs waiting their turn, each removable. Everything goes through one queue, whether it
  was started from the page, by the schedule or by an `update-now` file, so two runs never collide.
- **Library**: every comic with its page count and how its last run ended. Filter it with a name or a
  wildcard such as `Uncompressed/Snafu-Comics/*`, then update the checked comics, everything shown,
  or one comic from its own row.
- **Add comics**: a row per comic — where its pages go, where its archive goes, and the page to start
  from. Both folders are inside the ones named in Settings, so they are written once each:

  | Pages folder | Archive | First page |
  | --- | --- | --- |
  | `Snafu-Comics/nsma` | `Snafu-Comics/nsma.cbz` | `https://www.snafu-comics.com/nsma/issue-1-cover` |
  | `MyComic` | `MyComic/MyComic.cbz` | `https://example.com/comic/first-page` |

  **Make cbz** is one switch: whether this comic keeps archives at all. What shape they take is decided
  by whether it has chapters - one archive per chapter if it does, one of the lot if it does not. Turn it
  off and the pages are still saved, the chapters still worked out, and nothing is written until you turn
  it back on.

  A **chapter list** - the comic's own archive page - is optional, and turns a new comic into one archive
  per chapter as soon as it has been scraped: the scrape records which page is which as it goes, the
  archive page is read for the boundaries, and the single archive is given up once every page is checked
  to be in a chapter. Leave it blank and the comic is kept as one archive, as before.

  Leave the archive blank and it is worked out: a comic already inside a group folder gets its `.cbz`
  beside its siblings, and a comic with no folder of its own is given one, since some readers dislike
  archives sitting loose in a root folder. Paste a list to fill in several rows at once, splitting on
  `|`, tabs or spaces. Tick **prime only** to save just the first page of each, or leave it off to
  scrape the whole comic. A full scrape has no time limit, since a new comic can run to thousands of
  pages; a stalled page still ends on its own, and anything else can be stopped. The options apply to
  every row, so add comics that need different options as separate batches. A folder that is already a
  comic is refused.
- **Edit** on any comic opens its settings: the page the next update starts from, its page number,
  the archive path, the scraping options, and whether it has ended. Beside them are the pages held, the
  last file saved, where the last run stopped and why, and recent runs. So a comic that stopped on a
  broken page can be pointed at the page after it and set going again with **Save and update now**.
  A comic being scraped cannot be edited, since the run rewrites its metadata after every page. A save
  is refused if the file has changed since you opened it. Every change is recorded under
  `history.edits` in the metadata.
- **Edit** also takes a **chapter list**, which is how a comic already in the library becomes chaptered:
  save the address of its archive page, then **Work out chapters**. It walks the comic once if nothing
  records which page is which, reads the archive page, and writes one archive per chapter, giving up the
  single archive once every page is accounted for. A comic that has been walked before needs no second
  walk.
- **Settings** edits `config/ComicScraper.json`: the pages and archive folders, how many comics run at
  once, the time limit, and what the add form starts with. Anything fixed on the command line is marked
  as such, since that wins.
- **Element paths** opens the lists of XPaths every scrape tries, in the order it tries them: the
  comic image, and the next-page link. Add one, note what it is for, reorder them, or turn one off.
  Drag a row by its handle, or use the arrows, to change the order. **Check this page** loads any
  address in the scraper's own browser and says which paths match it,
  with an **add it** button beside each; when nothing matches, it suggests paths from the page's own
  images and links. Paths that came with the script can be turned off but not deleted, so a later
  version of the script cannot quietly reinstate one you did not want.
- **Log** and **Recent**: the updater's output as it happens, and what the last jobs did.

With `--web` and no `--schedule`, the updater stays running and only does what the page or an
`update-now` file asks.

There is no login unless you set `MIRROR_WEB_PASSWORD`, in which case the browser asks for it (any
username). Without one, anyone who can reach the port can start scrapes, so keep the port off the
internet. The page's actions only accept JSON, so a link or form on another site cannot trigger them.

`web_ui.html` is read fresh on every page load, so editing it needs no restart.

## Running in Docker

The image pins Chromium and a matching ChromeDriver together, so a host update cannot break the pair.

```sh
docker build -t comics-updater:1.0 .
docker compose up -d
docker compose logs -f
```

The build is a separate command on purpose, and `docker-compose.yml` has no `build:` key. QNAP
Container Station tries to build for itself when it finds one, from a context it does not have, and
leaves you with a second image entry holding nothing useful.

Edit `docker-compose.yml` before the first run:

- `volumes` — point it at your library, mounted as `/library`
- `TZ` — **required**, or the container runs on UTC and the schedule fires at the wrong hour
- `user` — set it to the owner of the library folder (`ls -n` shows the numbers), so scraped pages
  land readable to whatever shares them rather than owned by root
- `command` — the schedule and how many comics to update at once

This runs happily on a NAS. On QNAP Container Station, memory limits belong in Advanced Settings
rather than `mem_limit` in the compose file, which Container Station rejects. If `docker build` fails
with a permission error about a home directory, run it as `HOME=/tmp DOCKER_CONFIG=/tmp/.docker docker build ...`.

### Changing the scripts without rebuilding

Rebuilding an image to change one line is miserable, especially when the build has to happen over
ssh. Uncomment the second volume in `docker-compose.yml` and point it at the folder holding the
scripts and `web_ui.html`:

```yaml
      - /share/Container/ComicScraper:/app:ro
```

That mounts over the copies baked in at build time, so the `.py` files in that folder are what runs.
Edit them over a file share, and:

- **`mirror_base.py` needs nothing at all.** Every comic is launched as a fresh
  `python /app/mirror_base.py …` subprocess, so the next comic to run picks up the new file. Even a
  scheduled run already in progress will use it for the comics it has not reached yet.
- **`update_comics.py` and `web_ui.py` need a container restart**, since they are the long-running
  process. The Restart button in Container Station is enough; no ssh. `web_ui.html` needs nothing.
- **Settings and element paths need nothing.** They are read from `config/` before each run.
- **Adopting a new comic needs nothing.** The library is re-scanned at the start of every scheduled
  run, so a `mirror_metadata.json` written today joins tonight's run by itself.

After that the image only exists to carry Python, Chromium and ChromeDriver, and needs rebuilding
only when one of those should change.

One warning: an empty or missing host path here mounts an empty `/app` and nothing will start. Make
sure the scripts really are in that folder before uncommenting.

Rebuilding with a tag that is already in use leaves the previous image behind as `<none>`, which is
usually what an unexpected extra entry in the Container Station image list turns out to be.
`docker image prune` clears them.

Three environment variables override browser discovery, which is how the container points Selenium at
its bundled Chromium. They are deliberately not command line flags, so they never end up baked into a
comic's saved resume command:

- `MIRROR_BROWSER_BINARY`
- `MIRROR_DRIVER_BINARY`
- `MIRROR_BROWSER_ARGS`
- `MIRROR_PAGE_TIMEOUT` — seconds to let a page load before giving up, 60 by default. Selenium
  has no limit of its own, so without this a site that never finishes loading stalls the run and
  holds up every comic queued behind it. Raise it for a site that really is just slow.
- `MIRROR_BROWSER_IMAGES` — set to `1` to let the browser load images. Off by default: pages are
  downloaded with `requests`, and only element attributes are ever read out of the browser, so
  loading them there spends the bandwidth twice. Only useful for debugging an odd site.

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

## Working out which file came from which page

Chapters, and anything else that needs to know where a page sits in a comic, first need to know which
saved file came from which page. A comic scraped years ago under different filenames does not record
that, so `chapters.py` works it out:

```sh
python chapters.py index "D:/Comics/Uncompressed/MyComic"          # walk the comic, then line it up
python chapters.py align "D:/Comics/Uncompressed/MyComic"          # line up a walk already done
python chapters.py show  "D:/Comics/Uncompressed/MyComic"          # what the last alignment says
```

The walk follows the comic from its first page and **downloads nothing** - it only records each page's
address, image and title. It is written as it goes, so a walk that is stopped or times out carries on
from where it left off when run again. `--start URL` says where the comic begins, and `--first` follows
the comic's own first-page link when its metadata only records a later page.

Lining up then rests on three things, in order:

1. **Filenames**, for pages never renamed.
2. **Image sizes**, asked of the site with a HEAD request that downloads nothing. The bytes on disk are
   the bytes the site sent, so a size nothing else shares identifies a page whose file was renamed years
   ago. This is what makes an old comic recoverable at all.
3. **Counting**, for the stretches between two anchors that hold the same number of each.

Every placement is then checked against the site's own sizes. A size that differs proves nothing on its
own, since a comic that changed host serves re-encoded images; a size that belongs to a **different**
file in the folder is a real conflict and stops the alignment being called settled. Pages the comic has
and the folder does not are listed, and do not block anything - they are a gap in the collection, not a
misplacement.

The result is cached under `config/index/`. It can be deleted at any time; the walk rebuilds it.

## Chapters

A comic that reads in chapters can be kept as one archive per chapter rather than a single enormous
one, which is what most readers want and what a phone can actually open.

```sh
python chapters.py chapters "D:/Comics/Uncompressed/MyComic" --archive "https://example.com/archive/"
python chapters.py chapters "D:/Comics/Uncompressed/MyComic"          # from the addresses themselves
python chapters.py chapters "D:/Comics/Uncompressed/MyComic" --list starts.txt
python chapters.py pack "D:/Comics/Uncompressed/MyComic" --root "D:/Comics" --dry-run
```

To see how a page reads before committing to anything:

```sh
python chapters.py try "D:/Comics/Uncompressed/MyComic" --archive "https://example.com/archive/"
python chapters.py try . --archive "https://example.com/archive/" --like "https://example.com/comic/1"
```

It fetches that page and says how many of its links are pages of this comic and what it would read as
chapters, without walking anything and without saving. `--like` gives it one of the comic's page
addresses when the folder does not say, so a comic that has never been scraped can be checked too. An
archive with no chapter headings shows up as one enormous chapter, which is the sign to use another
source.

Working out where chapters start has three sources, all ending in the same list, and none of them
writes anything without `--save`:

1. **An archive page.** Its links are checked against the addresses the walk recorded, so a link is
   *known* to be a page of this comic rather than guessed at, and chapter titles come from whatever
   headings sit above them. Works on hand-built tables and on themed archives alike.
2. **The addresses themselves**, for a comic that counts `/c4/p7` or `/ss/4-7`: the chapter is the
   number that never goes down while another resets underneath it. A part that never changes is the
   comic's own name in the path, not a chapter.
3. **A file of chapter starts**, one address per line, each optionally followed by `|` and a title.

A chapter runs until the next one starts, so filler, guest art and flash pages stay where they were
published. Chapters are numbered in reading order whatever their labels say, which keeps a set of
specials labelled by year from being sorted to the end.

`--shift` moves every boundary, for an archive that labels a chapter after its first page.
`--browser` loads the archive page in the browser, for a page that builds itself with javascript.

### Packing

```sh
python chapters.py pack "D:/Comics/Uncompressed/MyComic" --root "D:/Comics"
python chapters.py pack "D:/Comics/Uncompressed/MyComic" --root "D:/Comics" --replace
```

Chapter archives go in the comic's own folder inside the archive shelf, named to sort:

```text
CBZs/Chalodillo/Las_Lindas/Las_Lindas - c001 - Chapter 1.cbz
CBZs/Chalodillo/Las_Lindas/Las_Lindas - c002 - Chapter 2.cbz
```

Each carries a `ComicInfo.xml` naming the series, the chapter number and how many there are, which is
what Kavita, Komga and PerfectViewer read. Only chapters whose pages have changed are written again,
so a nightly update rewrites one small archive rather than a gigabyte. Pages saved since the chapters
were worked out join the chapter still being published.

`--replace` gives up the single archive, but only after checking that **every page is in exactly one
chapter archive at the size it is on disk**; anything short of that leaves the old archive alone and
says why. It also turns off the single archive in the comic's settings, so a later scrape does not
build it again.

### Keeping chapters current

Once a comic is in chapters it keeps no single archive, so the pages a nightly update fetches would
sit in the folder and reach no archive at all. They do not have to:

- **A scrape adds each page it saves to the comic's index** - its address, the name it was saved as,
  its title and its real size - so the comic never has to be walked a second time.
- **After a chaptered comic gains pages, the updater lines them up and writes the chapter archives
  again**, which in practice rewrites the one chapter still being published.

Set `pack_chapters` to false in the settings, or pass `--no-pack-chapters`, to do it by hand instead;
the index is still kept up to date either way, so `chapters.py pack` picks the pages up whenever you
get to it.

**The comic remembers where its chapters are listed.** After it gains pages, the updater reads that page
again - after lining the new pages up, since a new chapter usually begins on one of them and could not be
placed before they existed. A change that only adds chapters at the end is taken; one that would move a
chapter whose archive already exists is reported and left alone, because pages would have to move between
archives. `chapters.py chapters <folder> --save --force` takes it once you have looked.

Running `chapters.py chapters <folder>` with no source at all re-reads whatever that comic remembers, so
keeping boundaries current needs no arguments.

## Settings

Settings live in a `config` folder beside the scripts, not in the library, so they survive the library
moving and a container can write them without touching your comics. `--config FOLDER` points somewhere
else, and `MIRROR_CONFIG` does the same for `mirror_base.py` on its own.

`config/ComicScraper.json`, every value optional:

```json
{
  "pages_folder": "Uncompressed",
  "cbz_folder": "CBZs",
  "jobs": 2,
  "timeout": 1800,
  "progress": 60,
  "max_depth": 5,
  "schedule": "03:30",
  "add_defaults": { "prefix": false, "increment": 1, "javascript": false, "waittime": 0,
                    "cbz": true, "direction_check": true, "prime": false }
}
```

Anything given on the command line wins over the file, and the **Settings** button on the web page
edits it. The file is re-read before every run, so a change takes effect on the next comic rather than
the next restart — except `schedule`, which the waiting loop reads once when it starts.

`pages_folder` and `cbz_folder` are what the **Add comics** table fills in for you, so a row only has to
say `MyComic`, not the whole path twice.

## Element paths

`mirror_base.py` ships with a list of XPaths for the comic image and a list for the next-page link, and
tries each in order until one matches. A library can add to them without editing the script, by keeping
a `config/element_paths.json` beside the scripts:

```json
{
  "image": [{ "xpath": "//img[@class=\"strip-art\"]", "note": "Odd Comic", "enabled": true }],
  "next":  [{ "xpath": "//*[@class=\"onwards\"]", "note": "Odd Comic", "enabled": true }]
}
```

The file decides the order and what is turned off; any path it does not mention still works and is tried
after the ones it lists, so a path added to the script later still arrives. A file that cannot be read is
reported and ignored rather than stopping the run.

`mirror_base.py` looks for it in the config folder, then in the folder it was started from and beside
itself, so a library that kept one of these in an older place goes on working. `MIRROR_ELEMENTS` names
the file outright.

To work out what a new comic needs:

```sh
python mirror_base.py --check "https://example.com/comic/some-page"
```

It loads the page, says which known paths match and which one a scrape would use, and when none match,
suggests paths from the images and links it can see. It saves nothing.

## The metadata file

`mirror_metadata.json` sits in each comic's folder and is packed into its archive. It is plain JSON,
meant to be edited by hand, and split into three parts:

```json
{
  "schema": 2,
  "settings": {
    "url":       "https://example.com/comic/412",
    "output":    "Uncompressed/MyComic",
    "cbz_path":  "CBZs/MyComic.cbz",
    "increment": 412,
    "prefix":    true,
    "javascript": false,
    "firefox":   false,
    "waittime":  0,
    "cbz":       true,
    "ended":     false
  },
  "state":   { "page_count": 412, "image_xpath": "...", "completed": false },
  "history": { "first_page_url": "...", "runs": [ ... ] }
}
```

**`settings` is the only part you edit, and the only part that decides anything.** The command is
built from it when a run starts, so changing `prefix` to `true` is the whole of turning numbering on
— there is no second copy of that fact to keep in step. Every key is written even at its default, so
there is always somewhere obvious to change it. `state` and `history` are what the scraper has
learned and done; they are rewritten each run.

Earlier versions stored the rendered command instead — as a list, as a string, and again inside every
run entry — which meant a hand edit had to be made in three or four places or it silently did
nothing. Files in that shape are still read, and

```sh
python adopt_comic.py --migrate --root "D:/Comics"
```

rewrites them all in the current shape. Add `--dry-run` to see what it would touch first. It is safe
to run twice; files already current are left alone.

Because the file is what marks a folder as a comic, moving a comic within the library is enough —
the updater notices the folder no longer matches the saved `output` and corrects it, rather than
believing stale metadata and scraping a fresh copy somewhere else.

To see the command a comic will actually run, without running it:

```sh
python update_comics.py "D:/Comics" --only MyComic --dry-run
```

## Notes and limits

- Sites that need a login, or that paginate with JavaScript only, will not work as-is. `-ej` enables
  JavaScript in the driver, which is off by default because pages load faster without it.
- The image and "next" element are found by trying a list of common XPaths. The one that works is
  remembered per comic. If a comic's newest page has different markup to every page before it — which
  happens, since many themes wrap the image in a link to the next page and the newest page has no next
  page — the search runs again rather than giving up.
- `-m` and `-n` let you supply the XPaths yourself for a site the guesses do not cover.
- Some comics wrap the page image in a link to the **previous** page, and some keep a next
  button on the last page pointing at the front page. Both make a scrape walk somewhere it
  should not: the first re-downloads the whole archive backwards under fresh numbers, the second
  looks like the site changed its layout. A run stops with code 8 if the page after the first is
  one the comic already holds, and treats a next link that climbs out of the comic's own folder
  as the end. `--no-direction-check` turns the first off for a comic that genuinely reuses its
  filenames.
- A page keeps one filename. Resuming re-saves the page it starts on, and if the name that lands
  differs from the one already there, the newer name wins and the older file is dropped from the
  folder and from the archive. That matters for comics whose pages were numbered by hand, or
  saved when an extension was appended to names that already had one.
- Be considerate: this drives a real browser against someone's site. `-w` sets a wait between pages.
- The browser is only ever asked for element attributes, never for rendered pixels, so it does not
  load images and does not wait for the load event. That makes a page that a browser renders
  instantly, but which keeps waiting on some third party font or script, stop being able to stall a
  run. It also roughly halves the traffic, since every page was previously fetched twice.

## Credits and license

`mirror_base.py` began as a script by **AChillVamp**, and a recognizable part of their work is still
in it. Everything since is built on that. Their archive.org page:
<https://archive.org/details/@achillvamp>

No license was attached to the original and none has been found, so this repository ships without a
license file rather than claiming a grant nobody can give. Read it, run it on your own comics, take
ideas from it. Redistribution and commercial use are not something anyone here is in a position to
permit. See [NOTICE](NOTICE) for the detail, including which parts are whose.

If you are AChillVamp, or know how to reach them, please get in touch — a licensing question is
waiting on it.
