// the library: what is being read at the top, then the library laid out by folder, series or author. the
// place being looked at is in the address, so the back button goes back up and a folder can be bookmarked
import { api, type ComicSummary } from "./api";
import { el, esc } from "./dom";
import { BROWSE_LABELS, type Browse, type Group, matches, nextIssues, pathLabel, reading, recentlyUpdated, shelf, upTo } from "./shelves";

export function browseHash(browse: Browse, path = ""): string {
  return path ? `#/browse/${browse}/${encodeURIComponent(path)}` : `#/browse/${browse}`;
}

const REMEMBERED = "reader.browse";

// how the library was last laid out on this device; only a convenience, so a browser that will not keep
// it just starts from folders
export function rememberedBrowse(): Browse {
  try {
    const saved = localStorage.getItem(REMEMBERED);
    if (saved === "folder" || saved === "series" || saved === "author" || saved === "all") return saved;
  } catch { /* storage refused: folders it is */ }
  return "folder";
}

function remember(browse: Browse) {
  try { localStorage.setItem(REMEMBERED, browse); } catch { /* nothing to keep it in */ }
}

let cached: ComicSummary[] | null = null;

export async function openLibrary(root: HTMLElement, browse: Browse, path: string,
                                  open: (id: string, at: number | null) => void): Promise<() => void> {
  remember(browse);
  root.innerHTML = "";
  const page = el("div", "library");
  page.innerHTML = `
    <header class="library-bar">
      <nav class="crumbs"></nav>
      <input type="search" placeholder="Find a comic" aria-label="Find a comic">
      <select aria-label="Arrange by">${(Object.keys(BROWSE_LABELS) as Browse[]).map((each) =>
        `<option value="${each}"${each === browse ? " selected" : ""}>${BROWSE_LABELS[each]}</option>`).join("")}</select>
      <button data-act="scan" title="Look for new pages now">Refresh</button>
    </header>
    <main></main>`;
  root.append(page);
  const main = page.querySelector("main")!;
  const search = page.querySelector<HTMLInputElement>('input[type="search"]')!;
  const arrange = page.querySelector<HTMLSelectElement>("select")!;
  let comics: ComicSummary[] = cached ?? [];

  // away from its own folder - in what is being read, a search, a series - a comic says which folder it is
  // from, since a shelf of archives named "Ch.01", "Ch.02" says nothing about which comic they are
  // under "recently updated", a comic says how many pages it gained and when, in place of what it says elsewhere
  function grewBy(comic: ComicSummary): string {
    const days = Math.floor((Date.now() / 1000 - (comic.grew ?? 0)) / 86400);
    const when = days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
    return `+${comic.added} page${comic.added === 1 ? "" : "s"} ${when}`;
  }

  // the next issues of series read to their ends, which count as new pages though never opened
  let next = new Set<string>();

  function card(comic: ComicSummary, away = true, growth = false): string {
    const badge = comic.new > 0 && comic.position !== null ? `<span class="badge new">${comic.new} new</span>`
      : next.has(comic.id) ? `<span class="badge new">${comic.pages} new</span>`
      : comic.position !== null && comic.unread > 0 ? `<span class="badge">${comic.unread} left</span>`
      : comic.ended && comic.position !== null && comic.unread <= 0 ? '<span class="badge done">Ended</span>' : "";
    const read = comic.position === null ? 0 : Math.round(((comic.position + 1) / Math.max(comic.pages, 1)) * 100);
    // under the title, whichever says most: which issue of which series, or who made it
    const issue = comic.series && comic.series !== comic.title
      ? `${comic.series}${comic.number ? ` #${comic.number}` : ""}` : comic.number ? `#${comic.number}` : "";
    const folder = away && comic.place ? comic.place.split("/").pop()! : "";
    const under = growth ? grewBy(comic)
      : [issue || folder || comic.author, `${comic.pages} pages`].filter(Boolean).join(" · ");
    return `<a class="card" href="#/read/${comic.id}" data-id="${comic.id}" title="${esc(comic.name)}">
      <div class="cover"><img loading="lazy" alt="" src="${api.coverUrl(comic.id, comic.cover)}">${badge}
        <button class="card-menu" type="button" aria-label="More for ${esc(comic.title)}" data-menu="${comic.id}">⋯</button></div>
      <div class="bar"><div style="width:${read}%"></div></div>
      <div class="name">${esc(comic.title)}</div>
      <div class="meta">${esc(under)}</div>
    </a>`;
  }

  function tile(group: Group): string {
    // a folder, a series or an author: the cover of the first comic in it, stacked, with how many there are
    // and how many have pages waiting
    const first = group.comics.find((comic) => comic.cover) ?? group.comics[0];
    const waiting = group.comics.filter((comic) => (comic.new > 0 && comic.position !== null) || next.has(comic.id)).length;
    return `<a class="card group" href="${browseHash(browse, group.key)}">
      <div class="cover stack"><img loading="lazy" alt="" src="${api.coverUrl(first.id, first.cover)}">
        <span class="badge count">${group.comics.length}</span>${waiting ? `<span class="badge new left">${waiting} updated</span>` : ""}
        <button class="card-menu" type="button" aria-label="More for ${esc(group.label)}" data-group="${esc(group.key)}">⋯</button></div>
      <div class="name">${esc(group.label)}</div>
      <div class="meta">${browse === "folder" ? "Folder" : browse === "series" ? "Series" : "Author"}</div>
    </a>`;
  }

  function section(title: string, body: string, count: number): string {
    return body ? `<section><h2>${title} <span>${count}</span></h2><div class="grid">${body}</div></section>` : "";
  }

  function crumbs() {
    const nav = page.querySelector(".crumbs")!;
    const parts: string[] = [`<a href="${browseHash(browse)}">Comics</a>`];
    if (path && browse === "folder") {
      const segments = path.split("/");
      segments.forEach((segment, at) => {
        parts.push(`<a href="${browseHash(browse, segments.slice(0, at + 1).join("/"))}">${esc(segment)}</a>`);
      });
    } else if (path) {
      parts.push(`<span>${esc(pathLabel(browse, path))}</span>`);
    }
    nav.innerHTML = parts.join('<span class="sep">›</span>');
  }

  function draw() {
    crumbs();
    next = nextIssues(comics);
    const query = search.value.trim();
    if (!comics.length) {
      main.innerHTML = '<p class="empty">No comics yet. The library is looked over every few minutes; Refresh looks now.</p>';
      return;
    }
    if (query) {
      const found = shelf(comics.filter((comic) => matches(comic, query)), "all", "").comics;
      main.innerHTML = section("Found", found.map((comic) => card(comic)).join(""), found.length) || '<p class="empty">Nothing by that name.</p>';
      return;
    }
    const here = shelf(comics, browse, path);
    if (path && !here.within.length) {
      main.innerHTML = `<p class="empty">Nothing here any more. <a href="${browseHash(browse)}">Back to the top</a></p>`;
      return;
    }
    // what is being read comes first, wherever you are: at the top for the whole library, and inside a
    // folder, series or author for what is being read there
    const now = reading(here.within);
    const recent = recentlyUpdated(here.within, Date.now() / 1000, now.updated);
    const groupsTitle = browse === "folder" ? "Folders" : browse === "series" ? "Series" : "Authors";
    main.innerHTML = section("New pages", now.updated.map((comic) => card(comic)).join(""), now.updated.length)
      + section("Continue reading", now.reading.map((comic) => card(comic)).join(""), now.reading.length)
      + section("Recently updated", recent.map((comic) => card(comic, true, true)).join(""), recent.length)
      + section(groupsTitle, here.groups.map(tile).join(""), here.groups.length)
      + section(browse === "all" ? "Every comic" : "Comics",
                here.comics.map((comic) => card(comic, browse !== "folder")).join(""), here.comics.length);
  }

  // what can be done to a comic besides reading it on: from the start, or marked read or unread, and to a
  // folder or series, all of it marked at once. done from here rather than inside the reader, which keeps
  // saving its place as it is read. a choice that marks anything draws the library again from the server
  type Choice = [label: string, act: () => Promise<unknown> | void, marks: boolean];
  let popup: HTMLElement | null = null;
  function closeMenu() {
    popup?.remove();
    popup = null;
  }

  function comicChoices(comic: ComicSummary): Choice[] {
    const choices: Choice[] = [
      ["Read from the start", () => open(comic.id, 0), false],
      ["Mark as read", () => api.saveProgress(comic.id, Math.max(comic.pages - 1, 0)), true],
    ];
    // inside a folder or series, everything before this one too - catching up on a comic started elsewhere.
    // never offered from a search, where the order on screen is not the shelf's
    const before = search.value.trim() ? [] : upTo(comics, browse, path, comic.id);
    if (before.length > 1) choices.push(["Mark as read up to here", () => api.markMany(before.map((each) => each.id), true), true]);
    if (comic.position !== null) choices.push(["Mark as unread", () => api.forgetProgress(comic.id), true]);
    return choices;
  }

  function groupChoices(group: Group): Choice[] {
    const ids = group.comics.map((each) => each.id);
    const choices: Choice[] = [["Mark all as read", () => api.markMany(ids, true), true]];
    if (group.comics.some((each) => each.position !== null)) {
      choices.push(["Mark all as unread", () => api.markMany(ids, false), true]);
    }
    return choices;
  }

  function openMenu(button: HTMLElement, choices: Choice[]) {
    closeMenu();
    popup = el("div", "card-pop");
    for (const [label, act, marks] of choices) {
      const choice = el("button");
      choice.textContent = label;
      choice.onclick = async (event) => {
        event.stopPropagation();
        closeMenu();
        await act();
        if (marks) {
          comics = cached = (await api.library()).comics;
          draw();
        }
      };
      popup.append(choice);
    }
    const box = button.getBoundingClientRect();
    popup.style.left = `${Math.min(box.left + window.scrollX, window.innerWidth - 200)}px`;
    popup.style.top = `${box.bottom + window.scrollY + 4}px`;
    document.body.append(popup);
  }

  const escape = (event: KeyboardEvent) => { if (event.key === "Escape") closeMenu(); };
  document.addEventListener("click", closeMenu);
  window.addEventListener("keydown", escape);

  main.addEventListener("click", (event) => {
    const more = (event.target as HTMLElement).closest<HTMLElement>(".card-menu");
    if (more) {
      event.preventDefault();
      event.stopPropagation();
      const comic = more.dataset.menu ? comics.find((each) => each.id === more.dataset.menu) : undefined;
      const group = more.dataset.group !== undefined
        ? shelf(comics, browse, path).groups.find((each) => each.key === more.dataset.group) : undefined;
      if (comic) openMenu(more, comicChoices(comic));
      else if (group) openMenu(more, groupChoices(group));
      return;
    }
    const link = (event.target as HTMLElement).closest<HTMLAnchorElement>("a.card[data-id]");
    if (!link) return;
    event.preventDefault();
    const comic = comics.find((each) => each.id === link.dataset.id);
    // a comic that has gained pages since it was read through opens on its first new page
    const at = comic && comic.new > 0 && comic.position !== null && comic.unread <= comic.new
      ? comic.position + 1 : null;
    open(link.dataset.id!, at);
  });
  search.addEventListener("input", draw);
  arrange.addEventListener("change", () => { location.hash = browseHash(arrange.value as Browse); });
  page.querySelector<HTMLButtonElement>('[data-act="scan"]')!.onclick = async (event) => {
    const button = event.target as HTMLButtonElement;
    button.disabled = true;
    button.textContent = "Looking…";
    try {
      await api.scan();
      comics = cached = (await api.library()).comics;
      draw();
    } finally {
      button.disabled = false;
      button.textContent = "Refresh";
    }
  };

  const done = () => {
    closeMenu();
    document.removeEventListener("click", closeMenu);
    window.removeEventListener("keydown", escape);
  };

  // the last answer is drawn at once, so going into a folder is instant, and replaced when the fresh one comes
  if (cached) draw();
  try {
    comics = cached = (await api.library()).comics;
  } catch (error) {
    if (!cached) main.innerHTML = `<p class="empty">Could not reach the reader: ${esc(String(error))}</p>`;
    return done;
  }
  draw();
  return done;
}
