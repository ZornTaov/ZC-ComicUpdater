// a comic's info page: what its ComicInfo says it is, the addresses it came from on the web - each to open or
// to copy - where it is kept in the library, and how the scraper's last update of it went
import { api, type ComicInfo } from "./api";
import { adderHtml, boxHtml, fieldOf, shownExtras, valueOf, type Said } from "./comicinfoform";
import { openCoverDialog } from "./coverdialog";
import { esc, fitClass, refusal } from "./dom";

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

// what the edit form starts from. a comic the scraper keeps says only what was said by hand, the rest worked
// out each time it is packed - shown greyed, as what an empty box means. an archive from elsewhere is its
// ComicInfo, all of which is someone's say. extras are the tags beyond the nine it has a row for
export function startingValues(info: ComicInfo): { values: Said; worked: Said; extras: string[] } {
  const values: Said = {};
  for (const [key, said] of Object.entries(info.scraped ? info.said : info.says)) {
    if (said !== undefined && said !== null && said !== "") values[key] = String(said);
  }
  const worked: Said = info.scraped ? { ...info.worked } : {};
  return { values, worked, extras: shownExtras(info.form, values, worked) };
}

export async function openInfo(root: HTMLElement, id: string, back: () => void, editNow = false): Promise<() => void> {
  root.innerHTML = '<p class="empty">Loading…</p>';
  let toastTimer: number | undefined;
  const keys = (event: KeyboardEvent) => {
    if (event.key === "Escape" && !(event.target as HTMLElement).closest("input, textarea")) back();
  };
  window.addEventListener("keydown", keys);
  const first = await api.info(id);
  draw(first);
  // opened from a comic's ⋯ menu to edit it: the form at once, if the comic can be edited at all
  if (editNow && first.editable) edit(first);
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
    const shape = info.form;
    const { values, worked, extras } = startingValues(info);
    // the tags beyond the nine on the form, and those taken off it, which are taken out when it is saved
    const shown = [...extras];
    const removed = new Set<string>();
    const section = root.querySelector<HTMLElement>(".info-edit")!;
    section.innerHTML = `
      <h2>What this comic is</h2>
      <p class="muted">${info.scraped
        ? "Kept in the comic's metadata and written into its archives now and at every update. Left empty, a box keeps what is worked out, shown greyed."
        : "Written into this archive's ComicInfo.xml. A box left empty is taken out of it."}
        Any other tag of the ComicInfo schema can be added at the end.</p>
      <form class="edit-form"><div class="edit-boxes"></div>
        <div class="form-actions">
          <button type="submit" class="primary">Save</button>
          <button type="button" data-act="cancel">Cancel</button>
          <span class="form-message" role="status"></span>
        </div>
      </form>`;
    const form = section.querySelector<HTMLFormElement>("form")!;
    const boxes = form.querySelector<HTMLElement>(".edit-boxes")!;
    const message = section.querySelector<HTMLElement>(".form-message")!;
    // what is typed is read back before the boxes are drawn again, so adding a tag keeps it
    const keep = () => {
      for (const key of shape.fields.map(([each]) => each).concat(shown)) values[key] = valueOf(form, key);
    };
    const drawBoxes = () => {
      boxes.innerHTML = shape.fields.map((field) => boxHtml(shape, field, { value: values[field[0]] ?? "", hint: worked[field[0]] }))
        .concat(shown.map((key) => boxHtml(shape, fieldOf(shape, key), { value: values[key] ?? "", hint: worked[key], removable: true })))
        .join("") + adderHtml(shape, shown);
    };
    drawBoxes();
    form.addEventListener("change", (event) => {
      const adder = (event.target as HTMLElement).closest<HTMLSelectElement>("[data-add]");
      if (!adder || !adder.value) return;
      const key = adder.value;
      keep();
      shown.push(key);
      // in the schema's order, as the archive will have them
      const order = shape.extra.map(([each]) => each);
      shown.sort((a, b) => order.indexOf(a) - order.indexOf(b));
      removed.delete(key);
      drawBoxes();
      form.querySelector<HTMLElement>(`[name="${key}"]`)?.focus();
    });
    form.addEventListener("click", (event) => {
      const remove = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-remove]");
      if (!remove) return;
      event.preventDefault();
      keep();
      const key = remove.dataset.remove!;
      shown.splice(shown.indexOf(key), 1);
      delete values[key];
      removed.add(key);
      drawBoxes();
    });
    section.querySelector<HTMLButtonElement>('[data-act="cancel"]')!.onclick = () => draw(info);
    form.onsubmit = async (event) => {
      event.preventDefault();
      keep();
      const said: Said = {};
      for (const [key] of shape.fields) {
        if (values[key]) said[key] = values[key];
      }
      // a tag beyond the nine is named either way, empty taking it out: one the form never showed is left be
      for (const key of shown) said[key] = values[key] ?? "";
      for (const key of removed) said[key] = "";
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
            <div class="cover"><img alt="" class="${fitClass(info.coverFit)}" src="${api.coverUrl(info.id, info.cover)}"></div>
            <div class="info-about">
              <h1>${esc(info.title)}</h1>
              ${info.name !== info.title ? `<div class="muted">${esc(info.name)}</div>` : ""}
              <dl>${rows}<dt>Pages</dt><dd>${info.pages}</dd>
                <dt>Status</dt><dd>${info.ended ? "Ended" : info.scraped ? "Kept up to date" : "As it is"}</dd></dl>
              <div class="info-actions">
                <a class="button primary" href="#/read/${info.id}">Read</a>
                <a class="button" href="#/read/${info.id}/1">From the start</a>
                ${info.editable ? '<button data-act="edit">Edit</button>' : ""}
                <button data-act="cover">Edit cover…</button>
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
    // the cover dialog; a cover changed there is shown at once, the page drawn again from what the server says
    root.querySelector<HTMLButtonElement>('[data-act="cover"]')!.onclick = () => openCoverDialog(
      { target: `comic:${info.id}`, label: info.title, comicId: info.id, pages: info.pages,
        fallback: api.coverUrl(info.id, info.cover) },
      async () => draw(await api.info(info.id)));
    root.querySelectorAll<HTMLButtonElement>("[data-copy]").forEach((button) => {
      button.onclick = async () => {
        const link = info.links[Number(button.dataset.copy)];
        notify(await copyText(link.url) ? "Copied" : "Could not copy; press and hold the address instead");
      };
    });
  }
}
