import { describe, expect, it } from "vitest";
import type { ManyInfo, Page } from "./api";
import { addable, boxHtml, type InfoForm } from "./comicinfoform";
import { changeOf, holding, shownKeys } from "./comicinfodialog";
import { chapterOf, chapterTarget, keyAction, pageAt, placeStrip, tapAction, trialKept, typedPage, viewOf, views, wanted } from "./layout";
import { clean, merged, scopeOf } from "./settings";
import { runLine, startingValues } from "./info";
import { coverMessage, refusal } from "./dom";
import { describeCover } from "./coverdialog";

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

  it("keeps up and down for moving the page a little, never turning it", () => {
    expect(keyAction("ArrowDown", false, "ltr")).toBe("down");
    expect(keyAction("ArrowUp", false, "rtl")).toBe("up");
    expect(keyAction("PageUp", false, "ltr")).toBe("back");
  });

  it("jumps to the ends, by ten with shift the same way round as the arrows, and by chapter with brackets", () => {
    expect(keyAction("Home", false, "ltr")).toBe("first");
    expect(keyAction("End", false, "rtl")).toBe("last");
    expect(keyAction("ArrowRight", true, "ltr")).toBe("ahead");
    expect(keyAction("ArrowLeft", true, "ltr")).toBe("behind");
    expect(keyAction("ArrowLeft", true, "rtl")).toBe("ahead");
    expect(keyAction("ArrowRight", true, "rtl")).toBe("behind");
    expect(keyAction("]", false, "rtl")).toBe("nextChapter");
    expect(keyAction("[", false, "ltr")).toBe("previousChapter");
  });
});

describe("jumps", () => {
  const starts = [0, 10, 20];
  it("go on to the next chapter's start, or leave the comic past its last", () => {
    expect(chapterTarget(starts, 3, true)).toBe(10);
    expect(chapterTarget(starts, 10, true)).toBe(20);
    expect(chapterTarget(starts, 25, true)).toBeNull();
    expect(chapterTarget([5, 10], 2, true)).toBe(5);
  });

  it("go back to the start of the chapter being read, and from there to the one before", () => {
    expect(chapterTarget(starts, 15, false)).toBe(10);
    expect(chapterTarget(starts, 10, false)).toBe(0);
    expect(chapterTarget(starts, 0, false)).toBeNull();
    expect(chapterTarget([5, 10], 5, false)).toBe(0);
    expect(chapterTarget([5, 10], 2, false)).toBeNull();
  });

  it("take a comic with no chapters inside it as one, so back goes to its start before the comic before", () => {
    expect(chapterTarget([], 4, true)).toBeNull();
    expect(chapterTarget([], 4, false)).toBe(0);
    expect(chapterTarget([], 0, false)).toBeNull();
  });

  it("read a typed page from one, kept within the comic", () => {
    expect(typedPage("12", 50)).toBe(11);
    expect(typedPage(" 1 ", 50)).toBe(0);
    expect(typedPage("0", 50)).toBe(0);
    expect(typedPage("999", 50)).toBe(49);
    expect(typedPage("", 50)).toBeNull();
    expect(typedPage("abc", 50)).toBeNull();
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
    // space above and below every page
    const spaced = placeStrip(pages, "width", 400, 1000, 10);
    expect([...spaced.tops]).toEqual([10, 130, 750]);
    expect(spaced.total).toBe(1160);
    const original = placeStrip(pages, "original", 400, 1000);
    expect([...original.widths].slice(0, 2)).toEqual([800, 800]);
    expect(original.widest).toBe(800);
  });

  it("know which chapter a page is in", () => {
    expect(chapterOf([0, 10, 20], 15)).toBe(1);
    expect(chapterOf([5, 10], 2)).toBe(-1);
  });
});

describe("the info page", () => {
  const run = { updated: null, pages_saved: 3, completed: true, stop_reason: "no next button", exit_code: 0 };
  it("says how the last update went in a line", () => {
    expect(runLine(run)).toBe("at an unknown time · 3 pages saved · caught up · no next button");
    expect(runLine({ ...run, pages_saved: 0, completed: false, exit_code: 4, stop_reason: null }))
      .toBe("at an unknown time · nothing new · stopped (exit 4)");
    expect(runLine(null)).toBe("");
  });

  const form: InfoForm = {
    fields: [["title", "Title", false], ["series", "Series", false], ["writer", "Writer", false], ["year", "Year", false]],
    extra: [["Volume", "Volume", false], ["Publisher", "Publisher", false], ["Format", "Format", false],
            ["Manga", "Manga (reading direction)", false]],
    numbers: ["year", "Volume"], choices: { Manga: ["Unknown", "No", "Yes", "YesAndRightToLeft"] },
  };
  const info = {
    id: "a", title: "MyComic", name: "MyComic", author: null, cover: null, coverChosen: false, coverFit: "fill" as const, kind: "archive", place: "", pages: 3,
    ended: false, links: [], folder: null, files: [], pageCount: null, lastRun: null, updated: null,
    version: null, editable: true, form,
    about: { title: "MyComic", series: "MyComic", web: "https://example.com/" },
    said: { writer: "SomeAuthor", year: 2014, Publisher: "SomePublisher" },
    says: { title: "MyComic", series: "MyComic", Manga: "YesAndRightToLeft" },
    worked: { title: "MyComic", series: "MyComic", web: "https://example.com/", Format: "Web Comic" },
  };

  it("starts editing a scraped comic from what was said by hand, with the rest greyed in", () => {
    expect(startingValues({ ...info, scraped: true })).toEqual({
      values: { writer: "SomeAuthor", year: "2014", Publisher: "SomePublisher" },
      worked: { title: "MyComic", series: "MyComic", web: "https://example.com/", Format: "Web Comic" },
      // the tags beyond the nine said or worked out, in the schema's order
      extras: ["Publisher", "Format"],
    });
  });

  it("starts editing an archive from elsewhere from everything its ComicInfo says", () => {
    const { values, extras } = startingValues({ ...info, scraped: false });
    expect(values).toEqual({ title: "MyComic", series: "MyComic", Manga: "YesAndRightToLeft" });
    expect(extras).toEqual(["Manga"]);
  });

  it("offers only the tags not on the form yet", () => {
    expect(addable(form, ["Publisher", "Manga"]).map(([key]) => key)).toEqual(["Volume", "Format"]);
  });

  it("draws a tag with a list of choices as a list, its empty choice saying what empty means", () => {
    const html = boxHtml(form, ["Manga", "Manga (reading direction)", false], { value: "No", hint: "mixed", removable: true });
    expect(html).toContain('<option value="">(mixed)</option>');
    expect(html).toContain("<option selected>No</option>");
    expect(html).toContain('data-remove="Manga"');
  });
});

describe("a folder's ComicInfo", () => {
  const form: InfoForm = { fields: [["title", "Title", false], ["writer", "Writer", false], ["genre", "Genre", false]],
                           extra: [["Publisher", "Publisher", false], ["LanguageISO", "Language", false]],
                           numbers: [], choices: {} };
  const many: ManyInfo = {
    comics: 3, scraped: 1, archives: 4, stamps: {}, form,
    fields: { writer: { value: null, mixed: true }, genre: { value: "Comedy", mixed: false },
              LanguageISO: { value: null, mixed: true } },
  };

  it("shows the nine but the title, then every other tag any comic says, in the form's order", () => {
    expect(shownKeys(many)).toEqual(["writer", "genre", "LanguageISO"]);
    expect(holding(many)).toBe("3 comics, 4 archives, 1 kept up to date by the scraper");
  });

  it("writes only what was changed: never a mixed box left empty, nor a box put back as it was", () => {
    expect(changeOf(many, "writer", "")).toBeNull();
    expect(changeOf(many, "writer", "SomeAuthor")).toBe("SomeAuthor");
    expect(changeOf(many, "genre", "Comedy")).toBeNull();
    // emptying a box every comic agreed on takes it out of every one
    expect(changeOf(many, "genre", "")).toBe("");
    expect(changeOf(many, "Publisher", "SomePublisher")).toBe("SomePublisher");
  });
});

describe("covers and refusals", () => {

  it("says where a cover went, or why it stayed in the reader", () => {
    expect(coverMessage({ shelf: "CBZs/MyComic.jpg", note: null })).toBe("Cover set, and saved as CBZs/MyComic.jpg");
    expect(coverMessage({ shelf: null, note: null })).toBe("Cover set");
    expect(coverMessage({ note: "kept in the reader only: it could not be written beside the comic (Permission denied)" }))
      .toBe("Cover set, kept in the reader only: it could not be written beside the comic (Permission denied)");
  });

  it("says what a cover is now, how it is turned, and where it is kept", () => {
    const state = { target: "folder:CBZs/SomeAuthor", v: "u1", chosen: true, how: "address" as const,
                    from: "https://example.com/logo.png", page: null, turn: 90, fit: "width" as const,
                    shelf: "CBZs/SomeAuthor/cover.png",
                    shelfable: true };
    expect(describeCover(state, false))
      .toBe("From https://example.com/logo.png, turned 90°. Saved on the shelf as CBZs/SomeAuthor/cover.png.");
    expect(describeCover({ ...state, how: "page", page: 3, turn: 0, shelf: null, shelfable: false }, true))
      .toBe("Page 3. Kept in the reader only: there is nowhere on the shelf for this one.");
    expect(describeCover({ ...state, chosen: false, how: null, from: null, turn: 0, shelf: null }, false))
      .toBe("The first comic's cover");
  });

  it("says why a change was refused in the server's own words", () => {
    expect(refusal(new Error('409 {"detail":"Try again in a few minutes."}'))).toBe("Try again in a few minutes.");
    expect(refusal(new Error("500 Internal Server Error"))).toBe("500 Internal Server Error");
  });
});

describe("a comic opened at random", () => {
  it("keeps its place once five pages are seen, or the last one is", () => {
    expect(trialKept(4, 3, 100)).toBe(false);
    expect(trialKept(5, 4, 100)).toBe(true);
    expect(trialKept(1, 99, 100)).toBe(true);
    // a comic shorter than five pages is kept only read to its end
    expect(trialKept(2, 1, 3)).toBe(false);
    expect(trialKept(3, 2, 3)).toBe(true);
  });
});

describe("settings", () => {
  it("lets a comic's own settings win over every comic's", () => {
    expect(merged({ fit: "width", direction: "ltr" }, { direction: "rtl" })).toMatchObject({ fit: "width", direction: "rtl", mode: "single" });
  });

  it("puts a series' settings between every comic's and one chapter's own", () => {
    expect(merged({ gap: 20, padding: 10, fit: "width" }, { fit: "original" }, { gap: 0, fit: "screen" }))
      .toMatchObject({ gap: 0, padding: 10, fit: "original" });
  });

  it("keeps a change for the nearest that has settings of its own", () => {
    expect(scopeOf({ gap: 0 }, { gap: 4 }, true)).toBe("comic");
    expect(scopeOf({}, { gap: 4 }, true)).toBe("series");
    expect(scopeOf({}, {}, true)).toBe("all");
    // what was kept for a series it is no longer part of says nothing
    expect(scopeOf({}, { gap: 4 }, false)).toBe("all");
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

