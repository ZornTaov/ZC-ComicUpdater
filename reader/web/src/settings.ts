// how a comic is read. kept on the server, once for every comic and again for any one comic that differs,
// so a phone and a tablet read the same comic the same way
export type Mode = "single" | "spread" | "webtoon";
export type Fit = "screen" | "width" | "height" | "original";

export interface Settings {
  mode: Mode;
  direction: "ltr" | "rtl";
  fit: Fit;
  background: string;
  // how far into each side a tap turns the page, as a share of the screen's width
  zone: number;
  // tapping the left side goes forward, for one-handed reading
  swapZones: boolean;
  // in spreads, the first page alone, as a printed book opens
  coverAlone: boolean;
  // pages fetched and decoded ahead of the one shown, and behind it
  ahead: number;
  behind: number;
}

export const defaults: Settings = {
  mode: "single",
  direction: "ltr",
  fit: "screen",
  background: "#000000",
  zone: 0.33,
  swapZones: false,
  coverAlone: true,
  ahead: 4,
  behind: 2,
};

export function merged(global: Partial<Settings>, comic: Partial<Settings>): Settings {
  return { ...defaults, ...clean(global), ...clean(comic) };
}

// only what this version knows, at sensible values, whatever an older or newer page stored
export function clean(given: Partial<Settings>): Partial<Settings> {
  const out: Partial<Settings> = {};
  if (given.mode === "single" || given.mode === "spread" || given.mode === "webtoon") out.mode = given.mode;
  if (given.direction === "ltr" || given.direction === "rtl") out.direction = given.direction;
  if (given.fit === "screen" || given.fit === "width" || given.fit === "height" || given.fit === "original") out.fit = given.fit;
  if (typeof given.background === "string" && /^#[0-9a-f]{6}$/i.test(given.background)) out.background = given.background;
  if (typeof given.zone === "number") out.zone = Math.min(0.45, Math.max(0.1, given.zone));
  if (typeof given.swapZones === "boolean") out.swapZones = given.swapZones;
  if (typeof given.coverAlone === "boolean") out.coverAlone = given.coverAlone;
  if (typeof given.ahead === "number") out.ahead = Math.min(12, Math.max(1, Math.round(given.ahead)));
  if (typeof given.behind === "number") out.behind = Math.min(6, Math.max(0, Math.round(given.behind)));
  return out;
}
