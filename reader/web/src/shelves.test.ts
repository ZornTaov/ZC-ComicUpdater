import { describe, expect, it } from "vitest";
import type { ComicSummary } from "./api";
import { compareComics, reading, shelf } from "./shelves";

const comic = (over: Partial<ComicSummary>): ComicSummary => ({
  id: over.name ?? over.title ?? "x", name: over.title ?? "x", title: "MyComic", series: null, number: null,
  volume: null, year: null, author: null, place: "", kind: "archive", pages: 10, position: null, unread: 10,
  new: 0, ended: false, read: null, updated: 0, chapters: 0, cover: null, ...over });

const titles = (list: ComicSummary[]) => list.map((each) => each.title);

describe("order", () => {
  it("reads a series by its numbers, 2 before 10, and everything else by name", () => {
    const list = [
      comic({ title: "Tenth", series: "MyComic", number: "10" }),
      comic({ title: "Apple Comic" }),
      comic({ title: "Second", series: "MyComic", number: "2" }),
      comic({ title: "Zebra Comic" }),
      comic({ title: "Half", series: "MyComic", number: "0.5" }),
    ];
    expect(titles(list.sort(compareComics))).toEqual(["Apple Comic", "Half", "Second", "Tenth", "Zebra Comic"]);
  });

  it("puts volumes before numbers", () => {
    const list = [comic({ title: "b", series: "S", volume: "2", number: "1" }), comic({ title: "a", series: "S", volume: "1", number: "9" })];
    expect(titles(list.sort(compareComics))).toEqual(["a", "b"]);
  });

  it("reads numbers in names as numbers", () => {
    expect(titles([comic({ title: "Part 10" }), comic({ title: "Part 9" })].sort(compareComics))).toEqual(["Part 9", "Part 10"]);
  });
});

describe("reading", () => {
  it("puts a comic read to the end that has since gained pages under new pages, and leaves out the unstarted and the caught up", () => {
    const now = reading([
      comic({ title: "updated", position: 9, unread: 2, new: 2, pages: 12 }),
      comic({ title: "part way", position: 3, unread: 8, new: 2, pages: 12 }),
      comic({ title: "unstarted" }),
      comic({ title: "caught up", position: 9, unread: 0 }),
    ]);
    expect([titles(now.updated), titles(now.reading)]).toEqual([["updated"], ["part way"]]);
  });
});

describe("folders", () => {
  const library = [
    comic({ title: "Top", place: "" }),
    comic({ title: "One", place: "Site A" }),
    comic({ title: "Two", place: "Site A" }),
    comic({ title: "Deep", place: "Site A/Extras", position: 1, unread: 5 }),
    comic({ title: "Other", place: "Site B" }),
  ];

  it("shows the folders below and the comics here", () => {
    const top = shelf(library, "folder", "");
    expect(top.groups.map((group) => [group.label, group.comics.length])).toEqual([["Site A", 3], ["Site B", 1]]);
    expect(titles(top.comics)).toEqual(["Top"]);
  });

  it("goes into a folder, keeping what is being read anywhere inside it", () => {
    const inside = shelf(library, "folder", "Site A");
    expect(inside.groups.map((group) => group.key)).toEqual(["Site A/Extras"]);
    expect(titles(inside.comics)).toEqual(["One", "Two"]);
    expect(titles(reading(inside.within).reading)).toEqual(["Deep"]);
  });

  it("does not take a folder for one whose name starts the same", () => {
    const list = [comic({ title: "a", place: "Site" }), comic({ title: "b", place: "Site Two" })];
    expect(titles(shelf(list, "folder", "Site").within)).toEqual(["a"]);
  });
});

describe("series and authors", () => {
  const library = [
    comic({ title: "Second", series: "MyComic", number: "2", author: "Someone" }),
    comic({ title: "First", series: "MyComic", number: "1", author: "Someone" }),
    comic({ title: "Standalone", author: "Someone Else" }),
    comic({ title: "Nobody's", author: null }),
  ];

  it("groups a series of more than one, and leaves a comic alone as a comic", () => {
    const top = shelf(library, "series", "");
    expect(top.groups.map((group) => group.label)).toEqual(["MyComic"]);
    expect(titles(top.comics)).toEqual(["Nobody's", "Standalone"]);
    expect(titles(shelf(library, "series", "MyComic").comics)).toEqual(["First", "Second"]);
  });

  it("never makes a series of comics that only share a name", () => {
    const twins = [comic({ title: "Same Name", place: "Uncompressed" }), comic({ title: "Same Name", place: "CBZs" })];
    const top = shelf(twins, "series", "");
    expect([top.groups.length, top.comics.length]).toEqual([0, 2]);
  });

  it("groups by author, with no author its own group only when there are several", () => {
    const top = shelf(library, "author", "");
    expect(top.groups.map((group) => group.label)).toEqual(["Someone"]);
    expect(titles(top.comics)).toEqual(["Nobody's", "Standalone"]);
  });
});
