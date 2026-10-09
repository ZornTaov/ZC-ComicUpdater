// the parts of reading that are only arithmetic, kept apart from the page so they can be tested alone:
// which pages are shown together, which way a tap turns, which pages to have ready
import type { Page } from "./api";
import type { Settings } from "./settings";

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
export function keyAction(key: string, shift: boolean, direction: "ltr" | "rtl"): Action | "first" | "last" | null {
  switch (key) {
    case "ArrowRight": return direction === "rtl" ? "back" : "forward";
    case "ArrowLeft": return direction === "rtl" ? "forward" : "back";
    case "PageDown": case "ArrowDown": case "Enter": return "forward";
    case "PageUp": case "ArrowUp": case "Backspace": return "back";
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

// the chapter a page is in
export function chapterOf(starts: number[], page: number): number {
  let found = -1;
  for (let at = 0; at < starts.length; at++) if (starts[at] <= page) found = at;
  return found;
}
