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
  chapters: number;
  cover: string | null;
}

export interface Page {
  v: string;
  w: number | null;
  h: number | null;
  standin: boolean;
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
  seen: number;
  chapters: Chapter[];
  pages: Page[];
  settings: Partial<Settings>;
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

function put<T>(path: string, body: unknown): Promise<T> {
  return call<T>(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  library: () => call<{ scanned: number | null; comics: ComicSummary[] }>("/api/library"),
  scan: () => call<{ scanned: number | null }>("/api/scan", { method: "POST" }),
  async comic(id: string): Promise<Comic> {
    // pages come as [version, width, height, stand-in] to keep a comic of thousands of pages one small answer
    const raw = await call<Omit<Comic, "pages"> & { pages: [string, number | null, number | null, number][] }>(
      `/api/comics/${id}`);
    return { ...raw, pages: raw.pages.map(([v, w, h, s]) => ({ v, w, h, standin: s === 1 })) };
  },
  pageUrl: (id: string, n: number, v: string) => `/api/comics/${id}/pages/${n}?v=${v}`,
  coverUrl: (id: string, v: string | null) => `/api/comics/${id}/cover${v ? `?v=${v}` : ""}`,
  standIn: (id: string, n: number) => call<StandIn>(`/api/comics/${id}/pages/${n}/standin`),
  saveProgress: (id: string, position: number) => put(`/api/comics/${id}/progress`, { position }),
  forgetProgress: (id: string) => call(`/api/comics/${id}/progress`, { method: "DELETE" }),
  settings: () => call<Partial<Settings>>("/api/settings"),
  saveSettings: (settings: Partial<Settings>) => put<Partial<Settings>>("/api/settings", settings),
  saveComicSettings: (id: string, settings: Partial<Settings>) => put(`/api/comics/${id}/settings`, settings),
};
