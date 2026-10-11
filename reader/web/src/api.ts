// the server's answers, typed, and the few calls the page makes
import type { Settings } from "./settings";

export interface ComicSummary {
  id: string;
  // what its file or folder is called, and what it is called to read: the ComicInfo's title where it has one
  name: string;
  title: string;
  series: string | null;
  number: string | null;
  volume: string | null;
  year: string | null;
  author: string | null;
  // the folder it is shown in, relative to the library; "" for the top
  place: string;
  kind: "archive" | "chapters" | "folder";
  pages: number;
  position: number | null;
  unread: number;
  new: number;
  ended: boolean;
  read: number | null;
  updated: number;
  // when a scan last saw it gain pages (seconds), and how many it gained then
  grew: number | null;
  added: number;
  chapters: number;
  // what the cover is a picture of now, so a new one has a new address; and whether one was chosen
  cover: string | null;
  coverChosen: boolean;
}

// the covers of folders, series and authors that have one of their own, by "folder:<path>" and so on:
// chosen in the reader, or a picture already on the shelf
export type GroupCovers = Record<string, { v: string; chosen: boolean }>;

// what a cover was set to: its new version, where on the shelf it was written, and anything to say about it
export interface CoverSet {
  target: string;
  v: string | null;
  shelf?: string | null;
  note: string | null;
}

export interface Page {
  v: string;
  w: number | null;
  h: number | null;
  standin: boolean;
  // a page held inside the archive as something other than a picture
  media: "video" | "flash" | "link" | null;
}

export interface Chapter {
  title: string;
  start: number;
}

export interface Comic {
  id: string;
  title: string;
  kind: string;
  ended: boolean;
  // where it is shelved, and the series and author it is in: what a page of it can be the cover of
  place: string;
  series: string | null;
  author: string | null;
  position: number;
  // how far down that page the reader was, as a share of it, for a comic read by scrolling
  part: number;
  seen: number;
  chapters: Chapter[];
  pages: Page[];
  settings: Partial<Settings>;
  // the parts either side of it in its series - the chapters of a comic, the issues of a series
  previous: { id: string; title: string } | null;
  next: { id: string; title: string } | null;
}

export interface StandIn {
  kind: "video" | "flash" | "link" | null;
  url?: string;
  address?: string;
  title?: string;
  name?: string;
}

// what the info page shows of a comic. about is its ComicInfo, said what its metadata keeps as said by hand
export interface ComicInfo {
  id: string;
  title: string;
  name: string;
  author: string | null;
  cover: string | null;
  coverChosen: boolean;
  kind: string;
  place: string;
  pages: number;
  ended: boolean;
  about: Partial<Record<"title" | "series" | "number" | "count" | "volume" | "summary" | "year" | "writer"
    | "penciller" | "genre" | "tags" | "web", string>>;
  said: Record<string, string | number>;
  scraped: boolean;
  links: { label: string; url: string }[];
  folder: string | null;
  files: string[];
  pageCount: number | null;
  lastRun: { updated: string | null; pages_saved: number | null; completed: boolean | null;
             stop_reason: string | null; exit_code: number | null } | null;
  updated: string | null;
  version: string | null;
  editable: boolean;
}

// what can be said about a comic on its info page, as its metadata's info block and ComicInfo call it
export const SAYABLE = ["title", "series", "summary", "year", "writer", "penciller", "genre", "tags", "web"] as const;
export type Said = Partial<Record<(typeof SAYABLE)[number], string>>;

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

// keepalive lets a save started as the window closes finish after the page is gone
function put<T>(path: string, body: unknown, keepalive = false): Promise<T> {
  return call<T>(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), keepalive });
}

export const api = {
  library: () => call<{ scanned: number | null; covers: GroupCovers; comics: ComicSummary[] }>("/api/library"),
  scan: () => call<{ scanned: number | null }>("/api/scan", { method: "POST" }),
  async comic(id: string): Promise<Comic> {
    // pages come as [version, width, height, stand-in, media] to keep a comic of thousands of pages one small answer
    const raw = await call<Omit<Comic, "pages"> & { pages: [string, number | null, number | null, number, Page["media"]][] }>(
      `/api/comics/${id}`);
    return { ...raw, pages: raw.pages.map(([v, w, h, s, media]) => ({ v, w, h, standin: s === 1, media: media ?? null })) };
  },
  info: (id: string) => call<ComicInfo>(`/api/comics/${id}/info`),
  // checked against what the page was showing, so a change made over one it never saw is refused
  saveInfo: (info: ComicInfo, said: Said) =>
    put<ComicInfo & { told: number }>(`/api/comics/${info.id}/info`, { info: said, updated: info.updated, version: info.version }),
  pageUrl: (id: string, n: number, v: string) => `/api/comics/${id}/pages/${n}?v=${v}`,
  coverUrl: (id: string, v: string | null) => `/api/comics/${id}/cover${v ? `?v=${v}` : ""}`,
  groupCoverUrl: (target: string, v: string) => `/api/covers?target=${encodeURIComponent(target)}&v=${v}`,
  // a page of a comic as the cover of that comic, or of a folder, series or author it is in
  chooseCover: (target: string, comic: string, page: number) => put<CoverSet>("/api/covers", { target, comic, page }),
  // a picture of one's own, sent as it is
  uploadCover: (target: string, file: Blob) => call<CoverSet>(`/api/covers/upload?target=${encodeURIComponent(target)}`,
    { method: "PUT", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }),
  resetCover: (target: string) => call<CoverSet>(`/api/covers?target=${encodeURIComponent(target)}`, { method: "DELETE" }),
  standIn: (id: string, n: number) => call<StandIn>(`/api/comics/${id}/pages/${n}/standin`),
  saveProgress: (id: string, position: number, part = 0, closing = false) =>
    put(`/api/comics/${id}/progress`, { position, part }, closing),
  forgetProgress: (id: string) => call(`/api/comics/${id}/progress`, { method: "DELETE" }),
  // many comics at once - a folder, a series, everything up to one - read to their ends or forgotten
  markMany: (ids: string[], read: boolean) => put<{ marked: number }>("/api/progress", { comics: ids, read }),
  settings: () => call<Partial<Settings>>("/api/settings"),
  saveSettings: (settings: Partial<Settings>) => put<Partial<Settings>>("/api/settings", settings),
  saveComicSettings: (id: string, settings: Partial<Settings>) => put(`/api/comics/${id}/settings`, settings),
};
