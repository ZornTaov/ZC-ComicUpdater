import { describe, expect, it } from "vitest";
import type { Page } from "./api";
import { chapterOf, keyAction, pageAt, placeStrip, tapAction, viewOf, views, wanted } from "./layout";
import { clean, merged } from "./settings";

const page = (w: number | null = 800, h: number | null = 1200, standin = false): Page => ({ v: "1", w, h, standin, media: null });

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

  it("find the page at the top of the screen in a long strip", () => {
    const tops = [0, 900, 1800, 1800, 2400, 5000];
    const strip = { length: tops.length, at: (n: number) => tops[n] };
    expect(pageAt(strip, 0)).toBe(0);
    expect(pageAt(strip, 899)).toBe(0);
    expect(pageAt(strip, 900)).toBe(1);
    // a page of no height yet shares its top with the next: the later one is where the reader is
    expect(pageAt(strip, 1800)).toBe(3);
    expect(pageAt(strip, 99999)).toBe(5);
    expect(pageAt({ length: 0, at: () => 0 }, 10)).toBe(0);
  });

  it("are placed one under the next by their measured sizes, for each fit", () => {
    const pages = [{ w: 800, h: 200 }, { w: 800, h: 1200 }, { w: null, h: null }];
    const width = placeStrip(pages, "width", 400, 1000);
    expect([...width.heights]).toEqual([100, 600, 400]);
    expect([...width.tops]).toEqual([0, 100, 700]);
    expect(width.total).toBe(1100);
    // fitted to the screen, a tall page shrinks to the screen's height and a strip stays as wide as allowed
    const screen = placeStrip(pages, "screen", 400, 300);
    expect([...screen.widths].slice(0, 2)).toEqual([400, 200]);
    expect([...screen.heights].slice(0, 2)).toEqual([100, 300]);
    const original = placeStrip(pages, "original", 400, 1000);
    expect([...original.widths].slice(0, 2)).toEqual([800, 800]);
    expect(original.widest).toBe(800);
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

  it("keeps side padding between none and 40% a side", () => {
    expect(clean({ padding: 75 })).toEqual({ padding: 40 });
    expect(clean({ padding: -5 })).toEqual({ padding: 0 });
    expect(clean({ padding: 12.4 })).toEqual({ padding: 12 });
  });
});

