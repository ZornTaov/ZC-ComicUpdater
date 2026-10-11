// a comic's info page: what its ComicInfo says it is, the addresses it came from on the web - each to open or
// to copy - where it is kept in the library, and how the scraper's last update of it went
import { api, type ComicInfo } from "./api";
import { esc } from "./dom";

// what the page shows of a ComicInfo, in this order, and what it calls each
export const FIELDS: [key: keyof ComicInfo["about"], label: string][] = [
  ["series", "Series"], ["number", "Number"], ["count", "Of"], ["volume", "Volume"], ["writer", "Writer"],
  ["penciller", "Artist"], ["year", "Year"], ["genre", "Genre"], ["tags", "Tags"],
];

// how the last update went, in a line
export function runLine(run: ComicInfo["lastRun"]): string {
  if (!run) return "";
  const when = run.updated ? new Date(run.updated).toLocaleString() : "at an unknown time";
  const saved = run.pages_saved ? `${run.pages_saved} page${run.pages_saved === 1 ? "" : "s"} saved` : "nothing new";
  const how = run.exit_code && run.exit_code !== 0 ? `stopped (exit ${run.exit_code})`
    : run.completed ? "caught up" : "not caught up";
  return [when, saved, how, run.stop_reason].filter(Boolean).join(" · ");
}

// copied by the clipboard where the page may use it, which a browser allows only over https or on this
// machine; otherwise by the older way, a selection copied, which still works over plain http on a nas
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* refused: try the older way */ }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  let done = false;
  try { done = document.execCommand("copy"); } catch { done = false; }
  area.remove();
  return done;
}

export async function openInfo(root: HTMLElement, id: string, back: () => void): Promise<() => void> {
  root.innerHTML = '<p class="empty">Loading…</p>';
  const info = await api.info(id);
  const about = info.about;
  const rows = FIELDS.filter(([key]) => about[key])
    .map(([key, label]) => `<dt>${label}</dt><dd>${esc(String(about[key]))}</dd>`).join("");
  const links = info.links.map((link, at) => `
    <li>
      <div class="link-label">${esc(link.label)}</div>
      <div class="link-row">
        <a class="link-url" href="${esc(link.url)}" target="_blank" rel="noopener noreferrer">${esc(link.url)}</a>
        <button data-copy="${at}">Copy</button>
      </div>
    </li>`).join("");
  const run = runLine(info.lastRun);
  root.innerHTML = `
    <div class="info">
      <header class="library-bar">
        <button data-act="back">‹ Back</button>
        <div class="info-title">${esc(info.title)}</div>
      </header>
      <main>
        <div class="info-top">
          <div class="cover"><img alt="" src="${api.coverUrl(info.id, info.cover)}"></div>
          <div class="info-about">
            <h1>${esc(info.title)}</h1>
            ${info.name !== info.title ? `<div class="muted">${esc(info.name)}</div>` : ""}
            <dl>${rows}<dt>Pages</dt><dd>${info.pages}</dd>
              <dt>Status</dt><dd>${info.ended ? "Ended" : info.scraped ? "Kept up to date" : "As it is"}</dd></dl>
            <div class="info-actions">
              <a class="button primary" href="#/read/${info.id}">Read</a>
              <a class="button" href="#/read/${info.id}/1">From the start</a>
            </div>
          </div>
        </div>
        ${about.summary ? `<section><h2>Summary</h2><p class="summary">${esc(about.summary)}</p></section>` : ""}
        <section><h2>On the web</h2>
          ${links ? `<ul class="links">${links}</ul>` : '<p class="muted">No address is known for this comic.</p>'}
        </section>
        <section><h2>In the library</h2>
          <dl>
            ${info.place ? `<dt>Shelved in</dt><dd>${esc(info.place)}</dd>` : ""}
            ${info.files.map((file, at) => `<dt>${at ? "" : info.files.length > 1 ? "Archives" : info.kind === "folder" ? "Pages" : "Archive"}</dt><dd class="path">${esc(file)}</dd>`).join("")}
            ${info.folder && info.kind !== "folder" ? `<dt>Pages</dt><dd class="path">${esc(info.folder)}</dd>` : ""}
            ${run ? `<dt>Last update</dt><dd>${esc(run)}</dd>` : ""}
          </dl>
        </section>
      </main>
      <div class="toast hidden"></div>
    </div>`;
  const toast = root.querySelector<HTMLElement>(".toast")!;
  let toastTimer: number | undefined;
  const notify = (text: string) => {
    toast.textContent = text;
    toast.classList.remove("hidden");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 1400);
  };
  root.querySelector<HTMLButtonElement>('[data-act="back"]')!.onclick = back;
  root.querySelectorAll<HTMLButtonElement>("[data-copy]").forEach((button) => {
    button.onclick = async () => {
      const link = info.links[Number(button.dataset.copy)];
      notify(await copyText(link.url) ? "Copied" : "Could not copy; press and hold the address instead");
    };
  });
  const keys = (event: KeyboardEvent) => { if (event.key === "Escape") back(); };
  window.addEventListener("keydown", keys);
  return () => {
    window.clearTimeout(toastTimer);
    window.removeEventListener("keydown", keys);
  };
}
