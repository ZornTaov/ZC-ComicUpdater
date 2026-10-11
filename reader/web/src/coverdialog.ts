// the cover of a comic, folder, series or author, changed in one place: a picture of your own, one from a web
// address, a page of the comic, turned a quarter at a time to stand up in a card shaped for a page, or put
// back as it was. shown in the card's own shape as it changes, so what fits is plain before closing
import { api, type CoverSet, type CoverState } from "./api";
import { coverMessage, el, esc, pickPicture, refusal } from "./dom";

export interface CoverTarget {
  // "comic:<id>", "folder:<path>", "series:<name>", "author:<name>"
  target: string;
  label: string;
  // for a comic: which, so a page of it can be the cover and its own cover shown
  comicId?: string;
  pages?: number;
  // what is shown with nothing chosen: the tile's own picture as the library has it
  fallback: string;
}

// what the dialog says the cover is now
export function describeCover(state: CoverState, isComic: boolean): string {
  const how: Record<string, string> = {
    picture: "A picture you put in",
    address: `From ${state.from ?? "a web address"}`,
    page: `Page ${state.page ?? "?"}`,
    shelf: "A picture already on the shelf",
    "first page": "The first page",
  };
  const said = (state.how && how[state.how]) || (isComic ? "The first page" : "The first comic's cover");
  const turned = state.turn ? `, turned ${state.turn}°` : "";
  const where = !state.chosen ? ""
    : state.shelf ? `. Saved on the shelf as ${state.shelf}.`
    : state.shelfable ? "." : ". Kept in the reader only: there is nowhere on the shelf for this one.";
  return `${said}${turned}${where}`;
}

export function openCoverDialog(cover: CoverTarget, changed: () => void): void {
  const isComic = cover.target.startsWith("comic:");
  const back = el("div", "dialog-back");
  back.innerHTML = `
    <div class="dialog" role="dialog" aria-modal="true" aria-label="Cover of ${esc(cover.label)}">
      <h2>Cover of ${esc(cover.label)}</h2>
      <div class="dialog-top">
        <div class="cover dialog-preview"><img alt=""></div>
        <div class="dialog-side">
          <p class="cover-state muted">Looking…</p>
          <div class="turns">
            <button data-turn="-90" title="Turn a quarter to the left">⟲ Rotate left</button>
            <button data-turn="90" title="Turn a quarter to the right">Rotate right ⟳</button>
          </div>
        </div>
      </div>
      <div class="dialog-row"><button data-act="upload">Upload a picture…</button></div>
      <form class="dialog-row" data-act="address">
        <input type="url" placeholder="A picture's web address, https://…" aria-label="A picture's web address">
        <button type="submit">Fetch</button>
      </form>
      ${isComic && cover.pages ? `<form class="dialog-row" data-act="page">
        <label>Page <input type="number" min="1" max="${cover.pages}" value="1" aria-label="Page number"></label>
        <button type="submit">Use page</button>
      </form>` : ""}
      <p class="form-message" role="status"></p>
      <div class="dialog-row end">
        <button data-act="reset">Reset</button>
        <button data-act="close" class="primary">Done</button>
      </div>
    </div>`;
  document.body.append(back);
  const dialog = back.querySelector<HTMLElement>(".dialog")!;
  const preview = dialog.querySelector<HTMLImageElement>(".dialog-preview img")!;
  const stateLine = dialog.querySelector<HTMLElement>(".cover-state")!;
  const message = dialog.querySelector<HTMLElement>(".form-message")!;
  const turns = [...dialog.querySelectorAll<HTMLButtonElement>("[data-turn]")];
  const reset = dialog.querySelector<HTMLButtonElement>('[data-act="reset"]')!;
  let touched = false;

  function urlOf(v: string | null): string {
    if (!v) return cover.fallback;
    return isComic ? api.coverUrl(cover.comicId!, v) : api.groupCoverUrl(cover.target, v);
  }

  async function refresh() {
    try {
      const state = await api.coverState(cover.target);
      preview.src = urlOf(state.v);
      stateLine.textContent = describeCover(state, isComic);
      turns.forEach((button) => { button.disabled = !state.chosen; });
      reset.disabled = !state.chosen;
    } catch (error) {
      stateLine.textContent = refusal(error);
    }
  }

  // every change goes through here: said while it happens, said when it is done, and the preview redrawn
  async function act(doing: string, work: () => Promise<CoverSet | null>, said = coverMessage) {
    message.textContent = doing;
    dialog.classList.add("busy");
    try {
      const set = await work();
      if (set) {
        touched = true;
        message.textContent = said(set);
      } else {
        message.textContent = "";
      }
      await refresh();
    } catch (error) {
      message.textContent = refusal(error);
    } finally {
      dialog.classList.remove("busy");
    }
  }

  function close() {
    back.remove();
    window.removeEventListener("keydown", keys);
    if (touched) changed();
  }
  const keys = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
  window.addEventListener("keydown", keys);
  back.addEventListener("click", (event) => { if (event.target === back) close(); });
  dialog.querySelector<HTMLButtonElement>('[data-act="close"]')!.onclick = close;
  dialog.querySelector<HTMLButtonElement>('[data-act="upload"]')!.onclick = () => act("Putting it in…", async () => {
    const file = await pickPicture();
    return file ? api.uploadCover(cover.target, file) : null;
  });
  const address = dialog.querySelector<HTMLFormElement>('[data-act="address"]')!;
  address.onsubmit = (event) => {
    event.preventDefault();
    const given = address.querySelector<HTMLInputElement>("input")!.value.trim();
    if (given) act("Fetching the picture…", () => api.coverFromAddress(cover.target, given));
  };
  const page = dialog.querySelector<HTMLFormElement>('[data-act="page"]');
  if (page) page.onsubmit = (event) => {
    event.preventDefault();
    const n = Number(page.querySelector<HTMLInputElement>("input")!.value);
    if (n >= 1) act("Using that page…", () => api.chooseCover(cover.target, cover.comicId!, n - 1));
  };
  turns.forEach((button) => {
    button.onclick = () => act("Turning it…", () => api.turnCover(cover.target, Number(button.dataset.turn)),
                                () => "Turned.");
  });
  reset.onclick = () => act("Putting it back…", () => api.resetCover(cover.target),
                            (set) => set.note ?? "Back to how it was.");
  refresh();
  dialog.querySelector<HTMLButtonElement>('[data-act="upload"]')!.focus();
}
