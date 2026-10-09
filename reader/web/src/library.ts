// the library: the comics with new pages first, then the ones part read, then everything else
import { api, type ComicSummary } from "./api";
import { el, esc } from "./dom";
import { matches, shelve } from "./shelves";

export async function openLibrary(root: HTMLElement, open: (id: string, at: number | null) => void): Promise<() => void> {
  root.innerHTML = "";
  const page = el("div", "library");
  page.innerHTML = `
    <header class="library-bar">
      <h1>Comics</h1>
      <input type="search" placeholder="Find a comic" aria-label="Find a comic">
      <button data-act="scan" title="Look for new pages now">Refresh</button>
    </header>
    <main></main>`;
  root.append(page);
  const main = page.querySelector("main")!;
  const search = page.querySelector<HTMLInputElement>('input[type="search"]')!;
  let comics: ComicSummary[] = [];

  function card(comic: ComicSummary): string {
    const badge = comic.new > 0 && comic.position !== null ? `<span class="badge new">${comic.new} new</span>`
      : comic.position !== null && comic.unread > 0 ? `<span class="badge">${comic.unread} left</span>`
      : comic.ended && comic.position !== null && comic.unread <= 0 ? '<span class="badge done">Ended</span>' : "";
    const read = comic.position === null ? 0 : Math.round(((comic.position + 1) / Math.max(comic.pages, 1)) * 100);
    return `<a class="card" href="#/read/${comic.id}" data-id="${comic.id}">
      <div class="cover"><img loading="lazy" alt="" src="${api.coverUrl(comic.id, comic.cover)}">${badge}</div>
      <div class="bar"><div style="width:${read}%"></div></div>
      <div class="name">${esc(comic.title)}</div>
      <div class="meta">${comic.pages} pages${comic.chapters ? ` · ${comic.chapters} ch` : ""}</div>
    </a>`;
  }

  function shelf(title: string, list: ComicSummary[]): string {
    return list.length ? `<section><h2>${title} <span>${list.length}</span></h2><div class="grid">${list.map(card).join("")}</div></section>` : "";
  }

  function draw() {
    const query = search.value.trim();
    const list = query ? comics.filter((comic) => matches(comic, query)) : comics;
    if (!comics.length) {
      main.innerHTML = '<p class="empty">No comics yet. The library is looked over every few minutes; Refresh looks now.</p>';
      return;
    }
    if (query) {
      main.innerHTML = shelf("Found", list) || '<p class="empty">Nothing by that name.</p>';
      return;
    }
    const shelves = shelve(list);
    main.innerHTML = shelf("New pages", shelves.updated) + shelf("Continue reading", shelves.reading)
      + shelf("Not started", shelves.unstarted) + shelf("Caught up", shelves.caughtUp) + shelf("Ended", shelves.finished);
  }

  main.addEventListener("click", (event) => {
    const link = (event.target as HTMLElement).closest<HTMLAnchorElement>("a.card");
    if (!link) return;
    event.preventDefault();
    const comic = comics.find((each) => each.id === link.dataset.id);
    // a comic that has gained pages since it was read through opens on its first new page
    const at = comic && comic.new > 0 && comic.position !== null && comic.unread <= comic.new
      ? comic.position + 1 : null;
    open(link.dataset.id!, at);
  });
  search.addEventListener("input", draw);
  page.querySelector<HTMLButtonElement>('[data-act="scan"]')!.onclick = async (event) => {
    const button = event.target as HTMLButtonElement;
    button.disabled = true;
    button.textContent = "Looking…";
    try {
      await api.scan();
      comics = (await api.library()).comics;
      draw();
    } finally {
      button.disabled = false;
      button.textContent = "Refresh";
    }
  };

  try {
    comics = (await api.library()).comics;
  } catch (error) {
    main.innerHTML = `<p class="empty">Could not reach the reader: ${esc(String(error))}</p>`;
    return () => undefined;
  }
  draw();
  return () => undefined;
}
