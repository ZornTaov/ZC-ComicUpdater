# ZC-ComicUpdater

Downloads a webcomic page by page, packs it into a `.cbz`, and remembers enough about the run to carry on
from where it stopped the next time. Point it at a library folder and it will update every comic in it
unattended, on a timer, in a container if you like.

The problem it solves is not the first download - it is the fifth year of updates. A comic you have been
following for a decade is a 250 MB archive, and adding this week's three pages should not mean rewriting
or re-syncing 250 MB. New pages are appended to the archive, so a sync carries only what is new.

It can also split a comic into one archive per chapter, adopt comics you already have, and be driven from
a small web page.

**Full documentation is in the [wiki](https://github.com/ZornTaov/ZC-ComicUpdater/wiki).**

## Requirements

- Python 3.9 or newer
- Chrome or Firefox installed (Selenium 4.6+ fetches the matching driver by itself)

```sh
pip install -r requirements.txt
```

Or skip all of that and use the container - see
[Docker](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Docker).

## Quick start

Grab one comic:

```sh
python mirror_base.py --output "Uncompressed/MyComic" "https://example.com/comic/first-page/"
```

Run the same command again later and it starts from the page it stopped on, adding only what is new.

Keep a whole library up to date, every night, with the web page on port 8080:

```sh
python update_comics.py "D:/Comics" --dry-run
python update_comics.py "D:/Comics" --schedule 03:30 --now --web 8080
```

Or in Docker:

```sh
docker build -t comics-updater:1.0 .
docker compose up -d
```

## Documentation

- [Home](https://github.com/ZornTaov/ZC-ComicUpdater/wiki) - what the scripts are, and where each old README section went
- [Installation and Quick Start](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Installation-and-Quick-Start) - flags, file naming, priming
- [Library Layout](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Library-Layout)
- [Adopting Comics](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Adopting-Comics)
- [Running Unattended](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Running-Unattended) - schedule, `update-now`, `restart`, exit codes
- [The Web Page](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/The-Web-Page)
- [Docker](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Docker)
- [Reader](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Reader) - a web reader for the library, in `reader/`
- [Archives and ComicInfo](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Archives-and-ComicInfo)
- [Page Index and Alignment](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Page-Index-and-Alignment)
- [Chapters](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Chapters)
- [Settings and Metadata](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Settings-and-Metadata)
- [Element Paths](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Element-Paths)
- [Notes and Limits](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Notes-and-Limits)
- [Contributing](https://github.com/ZornTaov/ZC-ComicUpdater/wiki/Contributing) - running the tests

## Credits and license

This project began as a webcomic-downloading script by **AChillVamp**
(<https://archive.org/details/@achillvamp>), and its core loop is theirs: find the comic's image by
trying a list of element paths, save it, press next, repeat. Everything built around that loop came
later. [NOTICE](NOTICE) has the details. If you are AChillVamp, or know how to reach them, please get
in touch.

Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). You're welcome to use it, change it
and share it for anything that isn't commercial.
