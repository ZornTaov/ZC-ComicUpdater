// the parts of reading that are only arithmetic, kept apart from the page so they can be tested alone:
// which pages are shown together, which way a tap turns, which pages to have ready
import type { Page } from "./api";
import type { Fit, Settings } from "./settings";

// what is on screen at once: one page, or two side by side. a page drawn as a spread, a stand-in, and the
// first page of a chapter always start a view of their own, so a chapter never opens on the wrong side
export function views(pages: Page[], settings: Pick<Settings, "mode" | "coverAlone">, chapterStarts: number[] = []): number[][] {
  if (settings.mode !== "spread") return pages.map((_, at) => [at]);
  const starts = new Set(chapterStarts);
  const alone = (at: number) => {
    const page = pages[at];
    return page.standin || (page.w !== null && page.h !== null && page.w > page.h * 1.2);
  };
  const out: number[][] = [];
  let at = 0;
  if (settings.coverAlone && pages.length > 0) {
    out.push([0]);
    at = 1;
  }
  while (at < pages.length) {
    const next = at + 1;
    if (alone(at) || next >= pages.length || alone(next) || starts.has(next)) {
      out.push([at]);
      at += 1;
    } else {
      out.push([at, next]);
      at += 2;
    }
  }
  return out;
}

export function viewOf(shown: number[][], page: number): number {
  for (let at = 0; at < shown.length; at++) if (shown[at].includes(page)) return at;
  return Math.max(0, Math.min(page, shown.length - 1));
}

export type Action = "forward" | "back" | "menu";

// what a tap at x does. reading right to left, the left side goes forward, as a page turned in a printed
// manga does; swapping the zones flips that again for a reader holding the device in the other hand
export function tapAction(x: number, width: number, settings: Pick<Settings, "zone" | "swapZones" | "direction">): Action {
  const side = x < width * settings.zone ? "left" : x > width * (1 - settings.zone) ? "right" : "middle";
  if (side === "middle") return "menu";
  const leftGoesForward = (settings.direction === "rtl") !== settings.swapZones;
  return (side === "left") === leftGoesForward ? "forward" : "back";
}

// what a key does, the same way round as the taps: the arrows follow the reading direction, everything
// else - space, page down, a page-turner's buttons - always goes forward
// up and down are for moving the page a little, to put it just where it reads best: never a turn
export function keyAction(key: string, shift: boolean, direction: "ltr" | "rtl"): Action | "first" | "last" | "up" | "down" | null {
  switch (key) {
    case "ArrowRight": return direction === "rtl" ? "back" : "forward";
    case "ArrowLeft": return direction === "rtl" ? "forward" : "back";
    case "ArrowDown": return "down";
    case "ArrowUp": return "up";
    case "PageDown": case "Enter": return "forward";
    case "PageUp": case "Backspace": return "back";
    case " ": return shift ? "back" : "forward";
    case "Home": return "first";
    case "End": return "last";
    case "m": case "Escape": return "menu";
    default: return null;
  }
}

// the pages to have fetched and decoded around a view, nearest first, so the next turn is instant
export function wanted(shown: number[][], view: number, ahead: number, behind: number): number[] {
  const out: number[] = [];
  for (let step = 1; step <= Math.max(ahead, behind); step++) {
    if (step <= ahead && view + step < shown.length) out.push(...shown[view + step]);
    if (step <= behind && view - step >= 0) out.push(...shown[view - step]);
  }
  return out;
}

// the page whose top is the last at or above y, among pages whose tops only ever go down the strip: found
// by halving, so it is quick however long the comic
export function pageAt(tops: { length: number; at(n: number): number }, y: number): number {
  let low = 0;
  let high = tops.length - 1;
  if (high < 0) return 0;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (tops.at(middle) <= y) low = middle;
    else high = middle - 1;
  }
  return low;
}

export interface Placed {
  tops: Float64Array;
  heights: Float64Array;
  widths: Float64Array;
  total: number;
  widest: number;
}

// where every page of a scrolled comic sits, worked out from the sizes the server measured rather than read
// back from the page: the four fits as the paged view has them, in `room` pixels across and `screen` tall.
// a page the server could not measure is given 40% of a screen until its picture says otherwise. `gap` is
// left empty above and below every page
export function placeStrip(pages: { w: number | null; h: number | null }[], fit: Fit, room: number, screen: number,
                           gap = 0): Placed {
  const count = pages.length;
  const placed: Placed = { tops: new Float64Array(count), heights: new Float64Array(count),
                           widths: new Float64Array(count), total: 0, widest: 0 };
  let y = 0;
  for (let n = 0; n < count; n++) {
    const { w, h } = pages[n];
    let width: number;
    let height: number;
    if (!w || !h) {
      width = room;
      height = screen * 0.4;
    } else if (fit === "width") {
      width = room;
      height = room * h / w;
    } else if (fit === "screen") {
      width = Math.min(room, screen * w / h);
      height = width * h / w;
    } else if (fit === "height") {
      height = screen;
      width = screen * w / h;
    } else {
      width = w;
      height = h;
    }
    y += gap;
    placed.tops[n] = y;
    placed.heights[n] = height;
    placed.widths[n] = width;
    placed.widest = Math.max(placed.widest, width);
    y += height + gap;
  }
  placed.total = y;
  return placed;
}

// the chapter a page is in
export function chapterOf(starts: number[], page: number): number {
  let found = -1;
  for (let at = 0; at < starts.length; at++) if (starts[at] <= page) found = at;
  return found;
}
