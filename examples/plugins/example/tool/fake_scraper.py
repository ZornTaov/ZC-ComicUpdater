#a stand-in for another program a plugin runs: it "scrapes" a made-up series by drawing its pages, so the
#example plugin can be tried, and tested, with nothing fetched from anywhere. it behaves the way such
#programs do - it writes into the folder it is run in, one archive or folder per chapter (or loose pages),
#each chapter's pages called 001.png, 002.png and so on, and it carries on from a chapter it is given by
#name, fetching that one again as it goes.
#
#it is a program of its own, as any plugin's would be: it shares nothing with the comic updater.
import argparse
import os
import struct
import sys
import time
import zipfile
import zlib


def png(width, height, colour):
    #a picture of one colour, small and different for every page, so no two pages are the same file
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    row = b"\x00" + bytes(colour) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def comic_info(series, number, chapters):
    #what a program like this says about each chapter, more than the updater would work out by itself
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ComicInfo>\n"
            "  <Title>Chapter {1}</Title>\n  <Series>{0}</Series>\n  <Number>{1}</Number>\n"
            "  <Count>{2}</Count>\n  <Notes>Drawn by the example plugin's scraper.</Notes>\n"
            "  <Publisher>Example Press</Publisher>\n  <LanguageISO>en</LanguageISO>\n"
            "  <Manga>YesAndRightToLeft</Manga>\n  <PageCount>9</PageCount>\n</ComicInfo>\n").format(
                series, number, chapters).encode("utf-8")


def main():
    params = argparse.ArgumentParser(description="Draws a made-up series into the folder it is run in.")
    params.add_argument("url", help="The series' address. Only its last part is used, as the series' name.")
    params.add_argument("--chapters", type=int, default=3, help="How many chapters the series has.")
    params.add_argument("--pages", type=int, default=2, help="How many pages each chapter has.")
    params.add_argument("--after", help="The chapter to carry on from, by name. It is fetched again too.")
    params.add_argument("--shape", choices=("cbz", "folders", "pages"), default="cbz",
                        help="An archive per chapter, a folder per chapter, or loose pages.")
    params.add_argument("--fail-after", type=int, help="Fail, as a broken site would, after this many chapters.")
    params.add_argument("--slow", type=float, default=0, help="Seconds to take over each chapter.")
    args = params.parse_args()

    series = args.url.rstrip("/").rsplit("/", 1)[-1] or "Series"
    start = 1
    if args.after:
        #carrying on from a chapter given by name, as a program that only knows chapters by their titles does
        start = int(args.after.rsplit(" ", 1)[-1])
    done = 0
    for number in range(start, args.chapters + 1):
        if args.fail_after is not None and done >= args.fail_after:
            print("could not read chapter {0}: the site said no".format(number), flush=True)
            return 3
        label = "Chapter {0}".format(number)
        pictures = [("{0:03d}.png".format(page), png(4 + page, 6, (number * 40 % 256, page * 60 % 256, 90)))
                    for page in range(1, args.pages + 1)]
        if args.shape == "cbz":
            #written aside and moved into place, as a careful program does
            with zipfile.ZipFile(label + ".cbz.part", "w") as zf:
                for name, body in pictures:
                    zf.writestr(name, body)
                zf.writestr("ComicInfo.xml", comic_info(series, number, args.chapters))
            os.replace(label + ".cbz.part", label + ".cbz")
        elif args.shape == "folders":
            os.makedirs(label, exist_ok=True)
            for name, body in pictures:
                with open(os.path.join(label, name), "wb") as f:
                    f.write(body)
        else:
            for name, body in pictures:
                with open("{0:03d}-{1}".format(number, name), "wb") as f:
                    f.write(body)
        print("fetched {0} ({1} pages)".format(label, len(pictures)), flush=True)
        done += 1
        if args.slow:
            time.sleep(args.slow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
