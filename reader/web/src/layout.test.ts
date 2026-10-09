import { describe, expect, it } from "vitest";
import type { ComicSummary, Page } from "./api";
import { chapterOf, keyAction, tapAction, viewOf, views, wanted } from "./layout";
import { clean, merged } from "./settings";
import { shelve } from "./shelves";

const page = (w: number | null = 800, h: number | null = 1200, standin = false): Page => ({ v: "1", w, h, standin });

describe("views", () => {
  it("shows one page at a time unless asked for two", () => {
    expect(views([page(), page(), page()], { mode: "single", coverAlone: true })).toEqual([[0], [1], [2]]);
  });

  it("pairs pages, with the first alone as a book opens", () => {
    expect(views(Array.from({ length: 5 }, () => page()), { mode: "spread", coverAlone: true }))
      .toEqual([[0], [1, 2], [3, 4]]);
    expect(views(Array.from({ length: 5 }, () => page()), { mode: "spread", coverAlone: false }))
      .toEqual([[0, 1], [2, 3], [4]]);
  });

  it("never pairs a page drawn as a spread, or a stand-in", () => {
    const pages = [page(), page(), page(2400, 1200), page(), page(), page(800, 1200, true), page()];
    expect(views(pages, { mode: "spread", coverAlone: false })).toEqual([[0, 1], [2], [3, 4], [5], [6]]);
  });

  it("starts each chapter on a view of its own", () => {
    const pages = Array.from({ length: 6 }, () => page());
    expect(views(pages, { mode: "spread", coverAlone: false }, [0, 3])).toEqual([[0, 1], [2], [3, 4], [5]]);
  });

  it("pairs pages whose size is not known", () => {
    expect(views([page(null, null), page(null, null)], { mode: "spread", coverAlone: false })).toEqual([[0, 1]]);
  });

  it("finds the view a page is in", () => {
    const shown = [[0], [1, 2], [3, 4]];
    expect(viewOf(shown, 2)).toBe(1);
    expect(viewOf(shown, 3)).toBe(2);
    expect(viewOf(shown, 99)).toBe(2);
  });
});

describe("taps and keys", () => {
  const ltr = { zone: 0.33, swapZones: false, direction: "ltr" as const };
  it("turns forward on the right, back on the left, and opens the menu between", () => {
    expect(tapAction(950, 1000, ltr)).toBe("forward");
    expect(tapAction(50, 1000, ltr)).toBe("back");
    expect(tapAction(500, 1000, ltr)).toBe("menu");
  });

  it("goes forward on the left reading right to left, and swapping flips it again", () => {
    expect(tapAction(50, 1000, { ...ltr, direction: "rtl" })).toBe("forward");
    expect(tapAction(50, 1000, { ...ltr, swapZones: true })).toBe("forward");
    expect(tapAction(50, 1000, { ...ltr, direction: "rtl", swapZones: true })).toBe("back");
  });

  it("has the arrows follow the reading direction and everything else go forward", () => {
    expect(keyAction("ArrowLeft", false, "rtl")).toBe("forward");
    expect(keyAction("ArrowRight", false, "ltr")).toBe("forward");
    expect(keyAction("PageDown", false, "rtl")).toBe("forward");
    expect(keyAction(" ", true, "ltr")).toBe("back");
    expect(keyAction("q", false, "ltr")).toBeNull();
  });
});

describe("pages made ready", () => {
  it("are the nearest ahead first, then behind", () => {
    const shown = [[0], [1], [2], [3], [4], [5]];
    expect(wanted(shown, 2, 3, 1)).toEqual([3, 1, 4, 5]);
    expect(wanted(shown, 5, 3, 1)).toEqual([4]);
  });

  it("know which chapter a page is in", () => {
    expect(chapterOf([0, 10, 20], 15)).toBe(1);
    expect(chapterOf([5, 10], 2)).toBe(-1);
  });
});

describe("settings", () => {
  it("lets a comic's own settings win over every comic's", () => {
    expect(merged({ fit: "width", direction: "ltr" }, { direction: "rtl" })).toMatchObject({ fit: "width", direction: "rtl", mode: "single" });
  });

  it("drops what it does not know and keeps numbers in range", () => {
    expect(clean({ fit: "sideways" as never, zone: 0.9, ahead: 100, background: "red" })).toEqual({ zone: 0.45, ahead: 12 });
  });
});

describe("shelves", () => {
  const comic = (over: Partial<ComicSummary>): ComicSummary => ({
    id: "x", title: "MyComic", kind: "archive", pages: 10, position: null, unread: 10, new: 0, ended: false,
    read: null, updated: 0, chapters: 0, cover: null, ...over });

  it("puts a comic read to the end that has since gained pages under new pages", () => {
    const shelves = shelve([comic({ position: 9, unread: 2, new: 2, pages: 12 })]);
    expect(shelves.updated).toHaveLength(1);
  });

  it("keeps a comic read part way under continue reading, new pages or not", () => {
    expect(shelve([comic({ position: 3, unread: 8, new: 2, pages: 12 })]).reading).toHaveLength(1);
  });

  it("tells a comic caught up apart from one that has ended", () => {
    const shelves = shelve([comic({ position: 9, unread: 0 }), comic({ position: 9, unread: 0, ended: true })]);
    expect([shelves.caughtUp.length, shelves.finished.length]).toEqual([1, 1]);
  });
});
