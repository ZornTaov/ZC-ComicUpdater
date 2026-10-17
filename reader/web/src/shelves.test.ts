import { describe, expect, it } from "vitest";
import type { ComicSummary } from "./api";
import { compareComics, editableTogether, grewBy, openingPage, randomPick, readShare, reading,recentlyUpdated, shelf, upTo } from "./shelves";

const comic = (over: Partial<ComicSummary>): ComicSummary => ({
  id: over.name ?? over.title ?? "x", name: over.title ?? "x", title: "MyComic", series: null, number: null,
  volume: null, year: null, author: null, place: "", kind: "archive", parent: null, pages: 10, position: null, unread: 10,
  new: 0, ended: false, read: null, updated: 0, grew: null, added: 0, chapters: 0, cover: null, coverChosen: false, coverFit: "fill", ...over });

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

  // a comic packed a hundred pages to an archive, read through to its last one
  const run = (next: Partial<ComicSummary>) => [
    comic({ title: "Pages 1-100", series: "MyComic", number: "1", place: "CBZs/MyComic", position: 99, unread: 0, read: 1000 }),
    comic({ title: "Pages 101-200", series: "MyComic", number: "2", place: "CBZs/MyComic", updated: 2000, ...next }),
  ];

  it("counts the next archive of a series read to its end as new pages, once it arrives after", () => {
    expect(titles(reading(run({})).updated)).toEqual(["Pages 101-200"]);
  });

  it("leaves out a next issue that was already there when the last was finished", () => {
    expect(reading(run({ updated: 500 })).updated).toEqual([]);
  });

  it("leaves out a next issue after one not read to its end, or one already opened", () => {
    const list = run({});
    list[0].unread = 3;
    expect(titles(reading(list).updated)).toEqual([]);
    expect(titles(reading(run({ position: 4, unread: 95 })).reading)).toEqual(["Pages 101-200"]);
  });

  it("only counts the issue straight after the one read, not every one past it", () => {
    const list = [...run({}), comic({ title: "Pages 201-300", series: "MyComic", number: "3", place: "CBZs/MyComic", updated: 3000 })];
    expect(titles(reading(list).updated)).toEqual(["Pages 101-200"]);
  });
});

describe("recently updated", () => {
  const now = 1_000_000_000;
  const day = 24 * 3600;
  it("lists comics that grew in the last two weeks, newest first, whether read or not", () => {
    const list = [
      comic({ id: "old", title: "old", grew: now - 30 * day, added: 4 }),
      comic({ id: "yesterday", title: "yesterday", grew: now - day, added: 2 }),
      comic({ id: "never", title: "never", grew: null }),
      comic({ id: "today", title: "today", grew: now - 60, added: 1, position: 3, unread: 6 }),
    ];
    expect(titles(recentlyUpdated(list, now))).toEqual(["today", "yesterday"]);
  });

  it("leaves out what is already shown under new pages", () => {
    const grown = comic({ id: "a", title: "a", grew: now - 60, added: 1 });
    expect(recentlyUpdated([grown], now, [grown])).toEqual([]);
  });

  it("says what it gained short enough for a cover's corner, and in full for its tooltip", () => {
    expect(grewBy(1, now - 60, now)).toEqual({ short: "+1 today", long: "+1 page today" });
    expect(grewBy(2, now - day - 60, now)).toEqual({ short: "+2 yesterday", long: "+2 pages yesterday" });
    expect(grewBy(12, now - 4 * day, now)).toEqual({ short: "+12 4d ago", long: "+12 pages 4 days ago" });
    //a clock a little behind the server's is still today, not "-1 days ago"
    expect(grewBy(1, now + 30, now).short).toBe("+1 today");
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

  it("reads up to a comic among those in the folder itself, not those in folders below it", () => {
    expect(titles(upTo(library, "folder", "Site A", "Two"))).toEqual(["One", "Two"]);
    expect(upTo(library, "folder", "Site A", "Deep")).toEqual([]);
  });

  it("counts a folder read by its pages, folders below it included", () => {
    const siteA = shelf(library, "folder", "").groups[0];
    // Deep is 2 of its 10 pages in; One and Two are never opened
    expect(readShare(siteA.comics)).toBe(7);
    const list = [comic({ title: "Long", pages: 990, position: 989 }), comic({ title: "Extra", pages: 10 })];
    expect(readShare(list)).toBe(99);
    expect(readShare([comic({ pages: 5, position: 9 })])).toBe(100);
    expect(readShare([comic({ pages: 0 })])).toBe(0);
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

  it("reads up to an issue in the series' own order, not the order the library came in", () => {
    const list = [...library, comic({ title: "Third", series: "MyComic", number: "3" })];
    expect(titles(upTo(list, "series", "MyComic", "Second"))).toEqual(["First", "Second"]);
    expect(titles(upTo(list, "series", "MyComic", "Third"))).toEqual(["First", "Second", "Third"]);
  });

  it("has nothing to read up to at the top, or for a comic not on this shelf", () => {
    expect(upTo(library, "series", "", "Second")).toEqual([]);
    expect(upTo(library, "series", "MyComic", "Standalone")).toEqual([]);
    expect(upTo(library, "all", "MyComic", "Second")).toEqual([]);
  });

  it("groups by author, with no author its own group only when there are several", () => {
    const top = shelf(library, "author", "");
    expect(top.groups.map((group) => group.label)).toEqual(["Someone"]);
    expect(titles(top.comics)).toEqual(["Nobody's", "Standalone"]);
  });
});

describe("random pick", () => {
  // draws given in turn: the first picks the folder, the second what is in it
  const draws = (...values: number[]) => () => values.shift() ?? 0;
  const picked = (list: ComicSummary[], ...values: number[]) => randomPick(list, "folder", "", draws(...values))?.id;
  const part = (n: number, over: Partial<ComicSummary> = {}) =>
    comic({ title: `Part ${n}`, series: "MyComic", number: String(n), place: "CBZs/MyComic", ...over });
  const read = { position: 9, unread: 0 };

  it("opens a series at its first part not read through", () => {
    expect(picked([part(1, read), part(2, read), part(3)])).toBe("Part 3");
  });

  it("counts from the start of a series, not on from the latest part read", () => {
    expect(picked([part(3, read), part(1), part(2)])).toBe("Part 1");
    expect(picked([part(1, read), part(2), part(3, read)])).toBe("Part 2");
  });

  it("opens a part read part way where it was left, and one grown since it was finished on its first new page", () => {
    expect(randomPick([part(1, { position: 4, unread: 5 })], "folder", "", draws())).toEqual({ id: "Part 1", at: null });
    const grown = comic({ title: "Grown", pages: 12, position: 9, unread: 2, new: 2 });
    expect(randomPick([grown], "folder", "", draws())).toEqual({ id: "Grown", at: 10 });
    expect(openingPage(grown)).toBe(10);
  });

  it("never picks what is read through, and has nothing when everything is", () => {
    const list = [part(1, read), part(2, read), comic({ title: "Done", ...read }), comic({ title: "Empty", pages: 0 })];
    expect(randomPick(list, "folder", "", draws())).toBeNull();
    expect(picked([...list, comic({ title: "Left" })], 0.99)).toBe("Left");
  });

  it("gives a folder of many one-shots the same chance as a comic on its own", () => {
    const oneShots = Array.from({ length: 40 }, (_, n) => comic({ title: `Fan ${n}`, place: "Fan Comics" }));
    const list = [...oneShots, comic({ title: "Lone" })];
    const low = picked(list, 0.1, 0.5);
    const high = picked(list, 0.9, 0.5);
    expect([low, high].filter((id) => id === "Lone")).toHaveLength(1);
    expect([low, high].filter((id) => id?.startsWith("Fan "))).toHaveLength(1);
  });

  it("picks only from inside the folder being browsed, and not from one whose name starts the same", () => {
    const list = [comic({ title: "In", place: "Site" }), comic({ title: "Next door", place: "Site B" }), comic({ title: "Top" })];
    for (const value of [0, 0.5, 0.99]) {
      expect(randomPick(list, "folder", "Site", draws(value, value))?.id).toBe("In");
    }
  });

  it("by series, picks within that series", () => {
    const list = [part(1, read), part(2), comic({ title: "Other" })];
    expect(randomPick(list, "series", "MyComic", draws(0.99, 0.99))?.id).toBe("Part 2");
  });
});

describe("which tiles offer the ComicInfo of everything in them", () => {
  const library = [
    comic({ title: "Packed", place: "CBZs/SomeAuthor" }),
    comic({ title: "Loose", place: "Uncompressed/SomeAuthor" }),
    comic({ title: "Elsewhere", place: "Manga" }),
  ];
  const tile = (browse: "folder" | "series" | "author", path: string, key: string) =>
    shelf(library, browse, path).groups.find((group) => group.key === key)!;

  it("not the library's own two trees, which hold every comic in it", () => {
    expect(editableTogether("folder", tile("folder", "", "CBZs"))).toBe(false);
    expect(editableTogether("folder", tile("folder", "", "Uncompressed"))).toBe(false);
  });

  it("but any folder inside them, and any other folder", () => {
    expect(editableTogether("folder", tile("folder", "CBZs", "CBZs/SomeAuthor"))).toBe(true);
    expect(editableTogether("folder", tile("folder", "Uncompressed", "Uncompressed/SomeAuthor"))).toBe(true);
    expect(editableTogether("folder", tile("folder", "", "Manga"))).toBe(true);
  });

  it("a series, never an author's comics", () => {
    const parts = [comic({ title: "One", series: "MyComic" }), comic({ title: "Two", series: "MyComic" })];
    expect(editableTogether("series", shelf(parts, "series", "").groups[0])).toBe(true);
    expect(editableTogether("author", { key: "SomeAuthor", label: "SomeAuthor", comics: parts })).toBe(false);
  });
});
