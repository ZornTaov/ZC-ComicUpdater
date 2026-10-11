// a comic's info page: what its ComicInfo says it is, the addresses it came from on the web - each to open or
// to copy - where it is kept in the library, and how the scraper's last update of it went
import { api, SAYABLE, type ComicInfo, type Said } from "./api";
import { coverMessage, esc, pickPicture } from "./dom";

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

// what each field of the edit form is called, and how big a box it gets
const FORM: [key: (typeof SAYABLE)[number], label: string, long?: boolean][] = [
  ["title", "Title"], ["series", "Series"], ["writer", "Writer"], ["penciller", "Artist"], ["year", "Year"],
  ["genre", "Genre"], ["tags", "Tags"], ["web", "Web address"], ["summary", "Summary", true],
];

// what the edit form starts from. a comic the scraper keeps says only what was said by hand, the rest worked
// out each time it is packed - shown greyed, as what an empty box means. an archive from elsewhere is its
// ComicInfo, all of which is someone's say
export function startingValues(info: ComicInfo): { values: Said; worked: Said } {
  const values: Said = {};
  const worked: Said = {};
  for (const key of SAYABLE) {
    const said = info.scraped ? info.said[key] : info.about[key];
    if (said !== undefined && said !== null && said !== "") values[key] = String(said);
    if (info.scraped && info.about[key]) worked[key] = String(info.about[key]);
  }
  return { values, worked };
}

// what a refusal says, out of the server's answer: its detail where it gave one
export function refusal(error: unknown): string {
  const text = String(error instanceof Error ? error.message : error);
  const body = text.replace(/^\d+\s+/, "");
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  } catch { /* not json: said as it came */ }
  return text;
}

export async function openInfo(root: HTMLElement, id: string, back: () => void): Promise<() => void> {
  root.innerHTML = '<p class="empty">Loading…</p>';
  let toastTimer: number | undefined;
  const keys = (event: KeyboardEvent) => {
    if (event.key === "Escape" && !(event.target as HTMLElement).closest("input, textarea")) back();
  };
  window.addEventListener("keydown", keys);
  draw(await api.info(id));
  return () => {
    window.clearTimeout(toastTimer);
    window.removeEventListener("keydown", keys);
  };

  function notify(text: string) {
    const toast = root.querySelector<HTMLElement>(".toast");
    if (!toast) return;
    toast.textContent = text;
    toast.classList.remove("hidden");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 1800);
  }

  function edit(info: ComicInfo) {
    const { values, worked } = startingValues(info);
    const fields = FORM.map(([key, label, long]) => {
      const value = esc(values[key] ?? "");
      const hint = worked[key] ? ` placeholder="${esc(worked[key]!)}"` : "";
      return `<label class="field${long ? " long" : ""}"><span>${label}</span>${long
        ? `<textarea name="${key}" rows="6"${hint}>${value}</textarea>`
        : `<input name="${key}" value="${value}"${hint}${key === "year" ? ' inputmode="numeric"' : ""}>`}</label>`;
    }).join("");
    const section = root.querySelector<HTMLElement>(".info-edit")!;
    section.innerHTML = `
      <h2>What this comic is</h2>
      <p class="muted">${info.scraped
        ? "Kept in the comic's metadata and written into its archives now and at every update. Left empty, a box keeps what is worked out, shown greyed."
        : "Written into this archive's ComicInfo.xml. A box left empty is taken out of it."}</p>
      <form class="edit-form">${fields}
        <div class="form-actions">
          <button type="submit" class="primary">Save</button>
          <button type="button" data-act="cancel">Cancel</button>
          <span class="form-message" role="status"></span>
        </div>
      </form>`;
    const form = section.querySelector<HTMLFormElement>("form")!;
    const message = section.querySelector<HTMLElement>(".form-message")!;
    section.querySelector<HTMLButtonElement>('[data-act="cancel"]')!.onclick = () => draw(info);
    form.onsubmit = async (event) => {
      event.preventDefault();
      const said: Said = {};
      for (const [key] of FORM) {
        const value = (form.elements.namedItem(key) as HTMLInputElement | HTMLTextAreaElement).value.trim();
        if (value) said[key] = value;
      }
      const save = form.querySelector<HTMLButtonElement>('[type="submit"]')!;
      save.disabled = true;
      message.textContent = "Saving…";
      try {
        const saved = await api.saveInfo(info, said);
        draw(saved);
        notify(saved.told ? `Saved, and written into ${saved.told} archive${saved.told === 1 ? "" : "s"}` : "Saved");
      } catch (error) {
        message.textContent = refusal(error);
        save.disabled = false;
      }
    };
    section.querySelector<HTMLInputElement>("input")?.focus();
  }

  function draw(info: ComicInfo) {
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
                ${info.editable ? '<button data-act="edit">Edit</button>' : ""}
                <button data-act="upload-cover">Set a cover picture…</button>
                ${info.coverChosen ? '<button data-act="reset-cover">Reset the cover</button>' : ""}
              </div>
            </div>
          </div>
          <section class="info-edit">${about.summary ? `<h2>Summary</h2><p class="summary">${esc(about.summary)}</p>` : ""}</section>
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
    root.querySelector<HTMLButtonElement>('[data-act="back"]')!.onclick = back;
    const editButton = root.querySelector<HTMLButtonElement>('[data-act="edit"]');
    if (editButton) editButton.onclick = () => edit(info);
    // a cover changed is shown at once: the page is drawn again from what the server now says
    const covered = async (set: Promise<{ shelf?: string | null; note: string | null } | null>, said: (s: { shelf?: string | null; note: string | null }) => string) => {
      try {
        const done = await set;
        if (!done) return;
        draw(await api.info(info.id));
        notify(said(done));
      } catch (error) {
        notify(refusal(error));
      }
    };
    root.querySelector<HTMLButtonElement>('[data-act="upload-cover"]')!.onclick = () => covered(
      pickPicture().then((file) => file ? api.uploadCover(`comic:${info.id}`, file) : null), coverMessage);
    const reset = root.querySelector<HTMLButtonElement>('[data-act="reset-cover"]');
    if (reset) reset.onclick = () => covered(api.resetCover(`comic:${info.id}`), (set) => set.note ?? "Cover reset");
    root.querySelectorAll<HTMLButtonElement>("[data-copy]").forEach((button) => {
      button.onclick = async () => {
        const link = info.links[Number(button.dataset.copy)];
        notify(await copyText(link.url) ? "Copied" : "Could not copy; press and hold the address instead");
      };
    });
  }
}
