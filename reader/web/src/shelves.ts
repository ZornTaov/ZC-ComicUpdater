// how the library is laid out, worked out apart from the page so it can be tested alone: what is being
// read at the top, then the library by folder, series or author, each in the order a reader expects -
// a series by its volumes and numbers, everything else by name with numbers read as numbers
import type { ComicSummary } from "./api";

export type Browse = "folder" | "series" | "author" | "all";

export const BROWSE_LABELS: Record<Browse, string> = { folder: "Folders", series: "Series", author: "Authors", all: "All" };

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function asNumber(text: string | null): number {
  const value = parseFloat(text ?? "");
  return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
}

// series first, so the issues of one sit together; then volume and number as numbers, so 2 comes before 10;
// then the title. a comic with no series sorts by its title among the series names
export function compareComics(a: ComicSummary, b: ComicSummary): number {
  return collator.compare(a.series ?? a.title, b.series ?? b.title)
    || asNumber(a.volume) - asNumber(b.volume)
    || asNumber(a.number) - asNumber(b.number)
    || collator.compare(a.title, b.title)
    || collator.compare(a.name, b.name);
}

export interface Reading {
  updated: ComicSummary[];
  reading: ComicSummary[];
}

// what is being read: comics read to the end that have since gained pages, and comics read part way
export function reading(comics: ComicSummary[]): Reading {
  const out: Reading = { updated: [], reading: [] };
  for (const comic of comics) {
    if (comic.position === null || comic.unread <= 0) continue;
    if (comic.new > 0 && comic.unread <= comic.new) out.updated.push(comic);
    else out.reading.push(comic);
  }
  out.updated.sort((a, b) => b.updated - a.updated);
  out.reading.sort((a, b) => (b.read ?? 0) - (a.read ?? 0));
  return out;
}

// comics that have gained pages lately, newest first: everything the library has been sent, read or not.
// those already under "new pages" - read to their end before they grew - are left there rather than shown twice
export const RECENT_DAYS = 14;

export function recentlyUpdated(comics: ComicSummary[], now: number, shown: ComicSummary[] = []): ComicSummary[] {
  const already = new Set(shown.map((comic) => comic.id));
  const since = now - RECENT_DAYS * 24 * 3600;
  return comics.filter((comic) => comic.grew !== null && comic.grew >= since && !already.has(comic.id))
    .sort((a, b) => (b.grew ?? 0) - (a.grew ?? 0));
}

export interface Group {
  key: string;
  label: string;
  comics: ComicSummary[];
}

export interface Shelf {
  // the comics this place holds, at any depth: what its "continue reading" is drawn from
  within: ComicSummary[];
  groups: Group[];
  comics: ComicSummary[];
}

function groupedBy(comics: ComicSummary[], key: (comic: ComicSummary) => string | null): Map<string, ComicSummary[]> {
  const out = new Map<string, ComicSummary[]>();
  for (const comic of comics) {
    const found = key(comic);
    if (found === null) continue;
    const list = out.get(found) ?? [];
    list.push(comic);
    out.set(found, list);
  }
  return out;
}

const UNKNOWN = "~unknown";

// one place in the library: a folder, a series, an author, or the top of any of them
export function shelf(comics: ComicSummary[], browse: Browse, path: string): Shelf {
  const byName = (groups: Group[]) => groups.sort((a, b) => collator.compare(a.label, b.label));
  if (browse === "all") return { within: comics, groups: [], comics: [...comics].sort(compareComics) };

  if (browse === "folder") {
    const within = path ? comics.filter((c) => c.place === path || c.place.startsWith(path + "/")) : comics;
    const below = groupedBy(within.filter((c) => c.place !== path), (c) => {
      const rest = path ? c.place.slice(path.length + 1) : c.place;
      return rest.split("/")[0];
    });
    const groups = [...below].map(([name, list]) => ({ key: path ? `${path}/${name}` : name, label: name, comics: list }));
    return { within, groups: byName(groups), comics: within.filter((c) => c.place === path).sort(compareComics) };
  }

  // series and authors: a group of one is just a comic, so it sits among the comics rather than behind a tile.
  // a series is only what a ComicInfo calls one - the issues of one comic, each its own archive - so a comic
  // with none is simply a comic, never grouped with another that happens to share its name
  const keyOf = browse === "series" ? (c: ComicSummary) => c.series : (c: ComicSummary) => c.author ?? UNKNOWN;
  if (path) {
    const within = comics.filter((c) => keyOf(c) === path);
    return { within, groups: [], comics: within.sort(compareComics) };
  }
  const groups: Group[] = [];
  const loose: ComicSummary[] = comics.filter((c) => keyOf(c) === null);
  for (const [key, list] of groupedBy(comics, keyOf)) {
    if (list.length > 1) groups.push({ key, label: key === UNKNOWN ? "Unknown author" : key, comics: list });
    else loose.push(...list);
  }
  return { within: comics, groups: byName(groups), comics: loose.sort(compareComics) };
}

// what a path is called, for the heading
export function pathLabel(browse: Browse, path: string): string {
  if (!path) return "Comics";
  if (browse === "author" && path === UNKNOWN) return "Unknown author";
  return browse === "folder" ? path.split("/").pop()! : path;
}

export function matches(comic: ComicSummary, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = [comic.title, comic.name, comic.series, comic.author, comic.place].join(" ").toLowerCase();
  return words.every((word) => text.includes(word));
}
