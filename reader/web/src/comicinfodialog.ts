// what a whole folder or series says it is, changed at once: each box shows what every comic in it says, or
// that they differ, and only the boxes changed are written - into every archive, each comic's title left its
// own. a comic the scraper keeps has it kept in its metadata too, so its next update says the same
import { api, type ManyInfo } from "./api";
import { adderHtml, boxHtml, fieldOf, type Said } from "./comicinfoform";
import { el, esc, refusal } from "./dom";
import { watchUnderway } from "./underway";

export interface ManyTarget {
  label: string;
  ids: string[];
}

// what the dialog says it is changing
export function holding(many: ManyInfo): string {
  const count = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;
  return [count(many.comics, "comic"), count(many.archives, "archive"),
          many.scraped ? `${many.scraped} kept up to date by the scraper` : ""].filter(Boolean).join(", ");
}

// the boxes shown, in the form's order: the nine but the title, then every other tag any comic here says
export function shownKeys(many: ManyInfo): string[] {
  return many.form.fields.concat(many.form.extra).map(([key]) => key).filter((key) => key in many.fields);
}

// whether a box now says something to write: a mixed box left empty, or any box back to what it said, does not
export function changeOf(many: ManyInfo, key: string, value: string): string | null {
  const field = many.fields[key];
  if (!field || field.mixed) return value === "" ? null : value;
  return value === (field.value ?? "") ? null : value;
}

export function openComicInfoDialog(target: ManyTarget, changed: () => void): void {
  const back = el("div", "dialog-back");
  back.innerHTML = `
    <div class="dialog wide" role="dialog" aria-modal="true" aria-label="ComicInfo of ${esc(target.label)}">
      <h2>ComicInfo of ${esc(target.label)}</h2>
      <p class="muted many-holds">Looking…</p>
      <p class="muted">Only what you change is written, into every archive here. A box saying <em>mixed</em> leaves
        each comic saying what it does, and × takes a tag out of every one. A comic the scraper keeps has it kept in
        its metadata as well, and for one of those an emptied box goes back to what is worked out. Each comic keeps
        its own title.</p>
      <form class="edit-form"><div class="edit-boxes"></div></form>
      <p class="form-message" role="status"></p>
      <div class="dialog-row end">
        <button data-act="close">Close</button>
        <button data-act="save" class="primary" disabled>Save</button>
      </div>
    </div>`;
  document.body.append(back);
  const dialog = back.querySelector<HTMLElement>(".dialog")!;
  const holds = dialog.querySelector<HTMLElement>(".many-holds")!;
  const form = dialog.querySelector<HTMLFormElement>("form")!;
  const boxes = form.querySelector<HTMLElement>(".edit-boxes")!;
  const message = dialog.querySelector<HTMLElement>(".form-message")!;
  const save = dialog.querySelector<HTMLButtonElement>('[data-act="save"]')!;
  let many: ManyInfo | null = null;
  let shown: string[] = [];
  // only what was changed: a value, or "" for a tag taken out of every comic
  let dirty: Said = {};
  let touched = false;

  function mark() {
    boxes.querySelectorAll<HTMLElement>("[data-field]").forEach((box) => {
      box.classList.toggle("changed", box.dataset.field! in dirty);
    });
    save.disabled = !Object.keys(dirty).length;
  }

  function drawBoxes() {
    if (!many) return;
    const now = many;
    boxes.innerHTML = shown.map((key) => {
      const field = now.fields[key];
      const cleared = dirty[key] === "";
      const value = key in dirty ? dirty[key] : field && !field.mixed ? field.value ?? "" : "";
      const hint = cleared ? "taken out of every one" : field?.mixed ? "mixed: each keeps its own" : "";
      return boxHtml(now.form, fieldOf(now.form, key), { value, hint, removable: true });
    }).join("") + adderHtml(now.form, shown);
    mark();
  }

  function show(found: ManyInfo) {
    many = found;
    shown = shownKeys(found);
    dirty = {};
    holds.textContent = holding(found);
    drawBoxes();
  }

  function close() {
    back.remove();
    window.removeEventListener("keydown", keys);
    if (touched) changed();
  }
  const keys = (event: KeyboardEvent) => {
    if (event.key === "Escape" && !(event.target as HTMLElement).closest("input, textarea, select")) close();
  };
  window.addEventListener("keydown", keys);
  back.addEventListener("click", (event) => { if (event.target === back) close(); });
  dialog.querySelector<HTMLButtonElement>('[data-act="close"]')!.onclick = close;

  const typed = (event: Event) => {
    const input = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    if (!many || !input.name) return;
    const change = changeOf(many, input.name, input.value.trim());
    if (change === null) delete dirty[input.name];
    else dirty[input.name] = change;
    mark();
  };
  form.addEventListener("input", typed);
  form.addEventListener("change", (event) => {
    const adder = (event.target as HTMLElement).closest<HTMLSelectElement>("[data-add]");
    if (!adder) {
      typed(event);
      return;
    }
    if (!adder.value || !many) return;
    const key = adder.value;
    const order = many.form.extra.map(([each]) => each);
    shown.push(key);
    shown.sort((a, b) => (order.indexOf(a) < 0 ? -1 : order.indexOf(a)) - (order.indexOf(b) < 0 ? -1 : order.indexOf(b)));
    drawBoxes();
    form.querySelector<HTMLElement>(`[name="${key}"]`)?.focus();
  });
  form.addEventListener("click", (event) => {
    const remove = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-remove]");
    if (!remove || !many) return;
    event.preventDefault();
    const key = remove.dataset.remove!;
    // a tag no comic here says, only just added, is just taken off the form again
    if (!(key in many.fields)) {
      shown.splice(shown.indexOf(key), 1);
      delete dirty[key];
    } else {
      dirty[key] = "";
    }
    drawBoxes();
  });
  form.onsubmit = (event) => event.preventDefault();

  save.onclick = async () => {
    if (!many || !Object.keys(dirty).length) return;
    save.disabled = true;
    dialog.classList.add("busy");
    message.textContent = "Writing…";
    try {
      const saving = api.saveManyInfo(target.ids, many.stamps, dirty);
      watchUnderway(saving);
      const saved = await saving;
      touched = true;
      show(saved);
      message.textContent = `Written into ${saved.told} archive${saved.told === 1 ? "" : "s"}${
        saved.comics > 1 ? ` of ${saved.comics} comics` : ""}.`;
    } catch (error) {
      message.textContent = refusal(error);
      mark();
    } finally {
      dialog.classList.remove("busy");
    }
  };

  api.manyInfo(target.ids).then(show, (error) => {
    holds.textContent = refusal(error);
  });
}
