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
  cover: string | null;
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
  library: () => call<{ scanned: number | null; comics: ComicSummary[] }>("/api/library"),
  scan: () => call<{ scanned: number | null }>("/api/scan", { method: "POST" }),
  async comic(id: string): Promise<Comic> {
    // pages come as [version, width, height, stand-in, media] to keep a comic of thousands of pages one small answer
    const raw = await call<Omit<Comic, "pages"> & { pages: [string, number | null, number | null, number, Page["media"]][] }>(
      `/api/comics/${id}`);
    return { ...raw, pages: raw.pages.map(([v, w, h, s, media]) => ({ v, w, h, standin: s === 1, media: media ?? null })) };
  },
  pageUrl: (id: string, n: number, v: string) => `/api/comics/${id}/pages/${n}?v=${v}`,
  coverUrl: (id: string, v: string | null) => `/api/comics/${id}/cover${v ? `?v=${v}` : ""}`,
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
