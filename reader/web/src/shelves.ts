// which shelf a comic sits on in the library, worked out apart from the page so it can be tested alone.
// a webcomic is never finished being read until the reader says it has ended, so the shelves are about what
// is new rather than what is done
import type { ComicSummary } from "./api";

export interface Shelves {
  updated: ComicSummary[];
  reading: ComicSummary[];
  unstarted: ComicSummary[];
  caughtUp: ComicSummary[];
  finished: ComicSummary[];
}

export function shelve(comics: ComicSummary[]): Shelves {
  const out: Shelves = { updated: [], reading: [], unstarted: [], caughtUp: [], finished: [] };
  for (const comic of comics) {
    if (comic.position === null) out.unstarted.push(comic);
    else if (comic.unread <= 0) (comic.ended ? out.finished : out.caughtUp).push(comic);
    // gained pages since it was last read, and the reader had got to the end of what there was then
    else if (comic.new > 0 && comic.unread <= comic.new) out.updated.push(comic);
    else out.reading.push(comic);
  }
  const recent = (a: ComicSummary, b: ComicSummary) => (b.read ?? 0) - (a.read ?? 0);
  out.updated.sort((a, b) => b.updated - a.updated);
  out.reading.sort(recent);
  out.caughtUp.sort(recent);
  out.finished.sort(recent);
  return out;
}

export function matches(comic: ComicSummary, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const title = comic.title.toLowerCase();
  return words.every((word) => title.includes(word));
}
