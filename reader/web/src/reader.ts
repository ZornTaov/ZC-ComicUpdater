// a comic open for reading: the page or pages on screen, the ones either side already decoded so a turn is
// instant, and the menu a tap in the middle brings up. where the reader is up to goes to the server as it
// changes, by page rather than by number, so it survives the comic growing or being renumbered.
import { api, type StandIn } from "./api";
import { attachGestures } from "./gestures";
import { chapterOf, chapterTarget, keyAction, tapAction, typedPage, viewOf, views, wanted } from "./layout";
import { Strip } from "./strip";
import { clean, merged, type Settings } from "./settings";
import { coverMessage, el, esc } from "./dom";
import { refusal } from "./info";
import { embedFor } from "./media";

const CACHE = 24;

export async function openReader(root: HTMLElement, id: string, startAt: number | null, leave: () => void): Promise<() => void> {
  const [comic, global] = await Promise.all([api.comic(id), api.settings().catch(() => ({}))]);
  let own: Partial<Settings> = clean(comic.settings || {});
  let globalSettings: Partial<Settings> = clean(global);
  let settings = merged(globalSettings, own);
  // a comic with settings of its own keeps changing those; otherwise a change is for every comic
  let scope: "comic" | "all" = Object.keys(own).length ? "comic" : "all";
  const starts = comic.chapters.map((chapter) => chapter.start);
  let shown = views(comic.pages, settings, starts);
  let view = viewOf(shown, clamp(startAt ?? comic.position, 0, comic.pages.length - 1));
  const images = new Map<number, HTMLImageElement>();
  let zoom = { scale: 1, x: 0, y: 0 };
  let saveTimer: number | undefined;
  let lastSaved = "";
  // false once the comic has been marked unread from inside it
  let keepingPlace = true;
  // how far down its page the reader was, for the first time a scrolled comic is shown
  let startPart = startAt === null ? comic.part || 0 : 0;

  root.innerHTML = "";
  const reader = el("div", "reader");
  const stage = el("div", "stage");
  const spread = el("div", "spread");
  stage.append(spread);
  const strip = el("div", "strip");
  const standinButton = el("button", "standin-open") as HTMLButtonElement;
  const menu = el("div", "menu hidden");
  const sheet = el("div", "sheet hidden");
  const player = el("div", "player hidden");
  const toast = el("div", "toast hidden");
  reader.append(stage, strip, standinButton, menu, sheet, player, toast);
  root.append(reader);

  function clamp(n: number, low: number, high: number) {
    return Math.max(low, Math.min(high, n));
  }

  function image(n: number): HTMLImageElement {
    let img = images.get(n);
    if (!img) {
      img = new Image();
      img.decoding = "async";
      img.draggable = false;
      img.alt = `page ${n + 1}`;
      img.src = api.pageUrl(comic.id, n, comic.pages[n].v);
      // decoded ahead, not only fetched: a picture still being decoded when it is shown is the stutter a
      // turn should never have
      img.decode().catch(() => undefined);
      images.set(n, img);
    }
    return img;
  }

  function keepNear(pages: number[]) {
    const keep = new Set(pages);
    for (const n of [...images.keys()]) {
      if (images.size <= CACHE) break;
      if (!keep.has(n)) images.delete(n);
    }
  }

  function page(): number {
    // the page the reader is up to: the last one on screen, so a spread read to the end counts as read
    const pages = shown[view];
    return pages[pages.length - 1];
  }

  function applyLook() {
    reader.style.background = settings.background;
    reader.style.setProperty("--pad", `${settings.padding}vw`);
    reader.dataset.mode = settings.mode;
    spread.className = `spread fit-${settings.fit} count-${shown[view]?.length ?? 1}${settings.direction === "rtl" ? " rtl" : ""}`;
  }

  function resetZoom() {
    zoom = { scale: 1, x: 0, y: 0 };
    spread.style.transform = "";
  }

  function render() {
    // a glide under way belongs to what was on screen, not to what is about to be
    stopGlide();
    if (settings.mode === "webtoon") return renderStrip();
    stage.hidden = false;
    strip.hidden = true;
    resetZoom();
    applyLook();
    const pages = shown[view];
    spread.replaceChildren(...pages.map(image));
    // a page taller or wider than the screen starts where it is read from: the top, and the right-hand
    // edge when reading right to left
    stage.scrollTop = 0;
    stage.scrollLeft = settings.direction === "rtl" ? stage.scrollWidth : 0;
    const near = wanted(shown, view, settings.ahead, settings.behind);
    near.forEach(image);
    keepNear([...pages, ...near]);
    showStandIn(pages);
    updateMenu();
    remember();
  }

  // webtoon: every page one under the next, scrolled through. strip.ts keeps only the pages near the screen
  // in the page, each at the place its measured size gives it
  let scrolling: Strip | null = null;

  function renderStrip() {
    stage.hidden = true;
    strip.hidden = false;
    standinButton.hidden = true;
    applyLook();
    if (!scrolling) {
      scrolling = new Strip(strip, comic.pages, {
        picture: image,
        release(n) {
          // a picture still on its way stops being fetched: a page flown past is not worth the wait
          const picture = images.get(n);
          if (picture && !picture.complete) picture.removeAttribute("src");
          images.delete(n);
        },
        play(n, _holder, stillWanted) {
          embedPage(n, stillWanted).then((left) => { if (left && stillWanted()) offer(left); });
        },
        reading(n) {
          if (n === page()) return;
          view = viewOf(shown, n);
          standinButton.hidden = true;
          updateMenu();
          remember();
        },
        moved: remember,
      });
    }
    scrolling.look(settings.fit, settings.padding, settings.gap);
    // opened again exactly where it was left: the same page, the same way down it
    scrolling.jumpTo(page(), startPart);
    startPart = 0;
    updateMenu();
  }

  // leaving scrolling: every player stopped, every picture let go
  function clearStrip() {
    scrolling?.destroy();
    scrolling = null;
  }

  // the place is saved as the reader goes, at most every 0.8s however fast they scroll - not only once they
  // stop, which a window closed mid-scroll never gets to
  function remember() {
    if (saveTimer !== undefined) return;
    saveTimer = window.setTimeout(() => { saveTimer = undefined; save(); }, 800);
  }

  // closing: the window going away, or hidden - a save sent as the page is torn down is kept alive by the
  // browser until it is done
  function save(closing = false) {
    if (!keepingPlace) return;
    const at = page();
    const part = settings.mode === "webtoon" && scrolling ? scrolling.partOf(at) : 0;
    const said = `${at}:${part.toFixed(3)}`;
    if (said === lastSaved) return;
    lastSaved = said;
    api.saveProgress(comic.id, at, part, closing).catch(() => { lastSaved = ""; });
  }

  // a page taller than the screen is read down before it is turned, as a reader of a printed page reads
  // to the bottom of it; only then does forward turn
  function scrolledThrough(forward: boolean): boolean {
    const vertical = stage.scrollHeight - stage.clientHeight > 4;
    const horizontal = stage.scrollWidth - stage.clientWidth > 4;
    if (vertical) {
      const at = headedTo(stage);
      const atEnd = forward ? at + stage.clientHeight >= stage.scrollHeight - 4 : at <= 4;
      if (!atEnd) {
        glideBy(stage, (forward ? 1 : -1) * stage.clientHeight * 0.85);
        return false;
      }
    } else if (horizontal) {
      const rtl = settings.direction === "rtl";
      const left = stage.scrollLeft <= 4;
      const right = stage.scrollLeft + stage.clientWidth >= stage.scrollWidth - 4;
      const atEnd = forward ? (rtl ? left : right) : (rtl ? right : left);
      if (!atEnd) {
        stage.scrollBy({ left: (forward !== rtl ? 1 : -1) * stage.clientWidth * 0.85 });
        return false;
      }
    }
    return true;
  }

  function turn(forward: boolean) {
    if (settings.mode === "webtoon") {
      // scrolled to the very end of a chapter, or the very start, a turn goes on into the next or the last.
      // judged by where a glide under way is headed, so a turn pressed while one is still easing to the end
      // goes on rather than waiting for it
      const at = headedTo(strip);
      if (forward && at + strip.clientHeight >= strip.scrollHeight - 2) return onward(true);
      if (!forward && at <= 2) return onward(false);
      glideBy(strip, (forward ? 1 : -1) * strip.clientHeight * 0.85);
      return;
    }
    if (zoom.scale > 1.01) {
      resetZoom();
      return;
    }
    if (!scrolledThrough(forward)) return;
    const next = view + (forward ? 1 : -1);
    if (next < 0 || next >= shown.length) return onward(forward);
    view = next;
    render();
  }

  // past the end of a chapter, its next chapter from the start; before its start, the one before from its
  // end - as a comic in chapters reads straight through. at the end of the last, the end
  // a jump to the chapter before opens it at its start, where a turn back opens it at its end
  function onward(forward: boolean, fromStart = forward) {
    const part = forward ? comic.next : comic.previous;
    if (!part) {
      if (!forward) return notify("This is the first page");
      return notify(comic.ended ? "The end" : "You're up to date");
    }
    window.clearTimeout(saveTimer);
    saveTimer = undefined;
    save(true);
    notify(part.title);
    location.hash = fromStart ? `#/read/${part.id}/1` : `#/read/${part.id}/999999`;
  }

  function go(n: number) {
    view = viewOf(shown, clamp(n, 0, comic.pages.length - 1));
    render();
  }

  // jumps are counted from the first page on screen: a chapter always starts a view of its own, so that
  // page is in the chapter being read, and back from a spread is back from what was read first
  function jumpBy(pages: number) {
    go(shown[view][0] + pages);
  }

  function jumpChapter(forward: boolean) {
    const target = chapterTarget(starts, shown[view][0], forward);
    if (target === null) return onward(forward, true);
    go(target);
  }

  let toastTimer: number | undefined;
  function notify(text: string) {
    toast.textContent = text;
    toast.classList.remove("hidden");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.add("hidden"), 1400);
  }

  // stand-ins: a page that is a video, a flash file or a link to a video is shown as the real thing in the
  // page's place - asked about once, then swapped in for the stand-in picture while it is on screen
  const asked = new Map<number, Promise<StandIn | null>>();
  function standInOf(n: number): Promise<StandIn | null> {
    if (!asked.has(n)) asked.set(n, api.standIn(comic.id, n).catch(() => null));
    return asked.get(n)!;
  }

  // the real thing in place of page n's picture; what could not be shown that way is handed back. asking
  // takes a moment, so by the time the answer comes the page may have been scrolled away: it is only put
  // in if still wanted
  async function embedPage(n: number, wanted: () => boolean = () => true): Promise<StandIn | null> {
    const found = await standInOf(n);
    if (!found?.kind) return null;
    const picture = images.get(n);
    // already showing the real thing, put there by whichever asked first
    if (!picture?.isConnected) return null;
    const embed = await embedFor(found);
    if (embed && picture?.isConnected && wanted()) {
      const info = comic.pages[n];
      if (info.w && info.h) embed.element.style.setProperty("--aspect", String(info.w / info.h));
      picture.replaceWith(embed.element);
      embed.start();
      return null;
    }
    return embed ? null : found;
  }

  async function showStandIn(pages: number[]) {
    standinButton.hidden = true;
    for (const n of pages.filter((at) => comic.pages[at].standin)) {
      const left = await embedPage(n);
      if (left && shown[view]?.includes(n)) offer(left);
    }
  }

  // a link to somewhere that cannot be embedded, or flash where Ruffle could not be loaded: a button opens it
  function offer(left: StandIn) {
    standinButton.hidden = false;
    standinButton.textContent = left.kind === "link" ? "Open link" : left.kind === "video" ? "Play video" : "Open flash file";
    standinButton.onclick = (event) => {
      event.stopPropagation();
      if (left.kind === "video" && left.url) playVideo(left.url);
      else if (left.kind === "link" && left.address) window.open(left.address, "_blank", "noopener");
      else if (left.url) window.open(left.url, "_blank", "noopener");
    };
  }

  function playVideo(url: string) {
    player.innerHTML = "";
    const video = document.createElement("video");
    video.src = url;
    video.controls = true;
    video.autoplay = true;
    video.playsInline = true;
    const close = el("button", "player-close");
    close.textContent = "×";
    close.onclick = () => { video.pause(); player.classList.add("hidden"); player.innerHTML = ""; };
    player.append(video, close);
    player.classList.remove("hidden");
  }

  // the menu: where you are, the chapters, and how the comic is shown
  function buildMenu() {
    const chapterOptions = comic.chapters.map((chapter, at) =>
      `<option value="${at}">${esc(chapter.title)}</option>`).join("");
    menu.innerHTML = `
      <header>
        <button data-act="back" aria-label="Library">‹ Library</button>
        <div class="title">${esc(comic.title)}</div>
        ${comic.chapters.length ? `<select data-act="chapter">${chapterOptions}</select>` : ""}
        <button data-act="info" aria-label="About this comic" title="About this comic">Info</button>
      </header>
      <footer>
        <div class="slider-row">
          <button data-act="first" title="First page (Home)" aria-label="First page">⏮</button>
          <button data-act="previousChapter" title="Previous chapter ([)" aria-label="Previous chapter">‹ Ch</button>
          <button data-act="behind" title="Back ten pages (Shift and arrow)" aria-label="Back ten pages">−10</button>
          <input type="range" min="0" max="${comic.pages.length - 1}" step="1" data-act="slider" aria-label="Page">
          <button data-act="ahead" title="On ten pages (Shift and arrow)" aria-label="On ten pages">+10</button>
          <button data-act="nextChapter" title="Next chapter (])" aria-label="Next chapter">Ch ›</button>
          <button data-act="last" title="Last page (End)" aria-label="Last page">⏭</button>
        </div>
        <div class="buttons">
          <label class="where">Page <input type="text" inputmode="numeric" data-act="page" aria-label="Go to page"> / ${comic.pages.length}</label>
          <button data-act="mode"></button>
          <button data-act="direction"></button>
          <button data-act="fit"></button>
          <button data-act="fullscreen">Full screen</button>
          <button data-act="cover">Cover…</button>
          <button data-act="more">More…</button>
        </div>
      </footer>`;
    menu.querySelector<HTMLButtonElement>('[data-act="back"]')!.onclick = () => { save(true); leave(); };
    // the place is saved first, so coming back from the info page opens the comic where it was left
    menu.querySelector<HTMLButtonElement>('[data-act="info"]')!.onclick = () => {
      save(true);
      location.hash = `#/info/${comic.id}`;
    };
    const chapterSelect = menu.querySelector<HTMLSelectElement>('[data-act="chapter"]');
    if (chapterSelect) chapterSelect.onchange = () => { go(comic.chapters[Number(chapterSelect.value)].start); };
    const slider = menu.querySelector<HTMLInputElement>('[data-act="slider"]')!;
    const pageBox = menu.querySelector<HTMLInputElement>('[data-act="page"]')!;
    slider.oninput = () => { pageBox.value = String(Number(slider.value) + 1); };
    slider.onchange = () => go(Number(slider.value));
    // a page typed in is gone to on enter, or on leaving the box; anything not a number puts back where
    // the reader is. the box lets go of the keyboard after, so the arrows turn pages again
    pageBox.onfocus = () => pageBox.select();
    pageBox.onchange = () => {
      const n = typedPage(pageBox.value, comic.pages.length);
      if (n === null) updateMenu();
      else go(n);
    };
    pageBox.onkeydown = (event) => {
      if (event.key === "Enter") pageBox.blur();
      if (event.key === "Escape") { pageBox.value = ""; pageBox.blur(); }
    };
    const jumps: Record<string, () => void> = {
      first: () => go(0),
      last: () => go(comic.pages.length - 1),
      behind: () => jumpBy(-10),
      ahead: () => jumpBy(10),
      previousChapter: () => jumpChapter(false),
      nextChapter: () => jumpChapter(true),
    };
    for (const [act, jump] of Object.entries(jumps)) {
      menu.querySelector<HTMLButtonElement>(`[data-act="${act}"]`)!.onclick = jump;
    }
    const cycle = <K extends keyof Settings>(key: K, values: Settings[K][]) => () => {
      const now = values.indexOf(settings[key]);
      change({ [key]: values[(now + 1) % values.length] } as Partial<Settings>);
    };
    menu.querySelector<HTMLButtonElement>('[data-act="mode"]')!.onclick = cycle("mode", ["single", "spread", "webtoon"]);
    menu.querySelector<HTMLButtonElement>('[data-act="direction"]')!.onclick = cycle("direction", ["ltr", "rtl"]);
    menu.querySelector<HTMLButtonElement>('[data-act="fit"]')!.onclick = cycle("fit", ["screen", "width", "height", "original"]);
    menu.querySelector<HTMLButtonElement>('[data-act="fullscreen"]')!.onclick = toggleFullscreen;
    menu.querySelector<HTMLButtonElement>('[data-act="more"]')!.onclick = openSheet;
    menu.querySelector<HTMLButtonElement>('[data-act="cover"]')!.onclick = openCoverSheet;
    menu.addEventListener("pointerdown", (event) => event.stopPropagation());
  }

  function updateMenu() {
    if (menu.classList.contains("hidden")) return;
    const at = page();
    const slider = menu.querySelector<HTMLInputElement>('[data-act="slider"]');
    if (slider) slider.value = String(at);
    // not while a page is being typed into it
    const pageBox = menu.querySelector<HTMLInputElement>('[data-act="page"]');
    if (pageBox && document.activeElement !== pageBox) pageBox.value = String(at + 1);
    // what has nowhere to go is greyed: no page before the first, no chapter before the first of the first
    const first = shown[view][0];
    const disable = (act: string, off: boolean) => {
      const button = menu.querySelector<HTMLButtonElement>(`[data-act="${act}"]`);
      if (button) button.disabled = off;
    };
    disable("first", first === 0);
    disable("behind", first === 0);
    disable("last", at === comic.pages.length - 1);
    disable("ahead", at === comic.pages.length - 1);
    disable("previousChapter", chapterTarget(starts, first, false) === null && !comic.previous);
    disable("nextChapter", chapterTarget(starts, first, true) === null && !comic.next);
    const chapterSelect = menu.querySelector<HTMLSelectElement>('[data-act="chapter"]');
    if (chapterSelect) chapterSelect.value = String(Math.max(0, chapterOf(starts, at)));
    const label = (act: string, text: string) => {
      const button = menu.querySelector<HTMLButtonElement>(`[data-act="${act}"]`);
      if (button) button.textContent = text;
    };
    label("mode", { single: "One page", spread: "Two pages", webtoon: "Scroll" }[settings.mode]);
    label("direction", settings.direction === "rtl" ? "Right to left" : "Left to right");
    label("fit", { screen: "Fit screen", width: "Fit width", height: "Fit height", original: "Actual size" }[settings.fit]);
  }

  function toggleMenu(show?: boolean) {
    const hidden = show === undefined ? !menu.classList.contains("hidden") : !show;
    menu.classList.toggle("hidden", hidden);
    if (!hidden) updateMenu();
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen().catch(() => notify("Full screen is not allowed here"));
  }

  function change(changes: Partial<Settings>) {
    const at = page();
    if (scope === "comic") {
      own = { ...own, ...changes };
      api.saveComicSettings(comic.id, own).catch(() => notify("Could not save the setting"));
    } else {
      globalSettings = { ...globalSettings, ...changes };
      api.saveSettings(globalSettings).catch(() => notify("Could not save the setting"));
    }
    const wasWebtoon = settings.mode === "webtoon";
    settings = merged(globalSettings, own);
    shown = views(comic.pages, settings, starts);
    view = viewOf(shown, at);
    if (wasWebtoon && settings.mode !== "webtoon") clearStrip();
    render();
  }

  function openSheet() {
    sheet.innerHTML = `
      <h2>Reading settings</h2>
      <label class="row">Remember for
        <select data-set="scope"><option value="all">every comic</option><option value="comic">this comic only</option></select></label>
      <label class="row">Background <input type="color" data-set="background"></label>
      <label class="row">Side padding <span class="value" data-show="padding"></span>
        <input type="range" min="0" max="40" step="1" data-set="padding"></label>
      <label class="row">Space above and below pages <span class="value" data-show="gap"></span>
        <input type="range" min="0" max="120" step="2" data-set="gap"></label>
      <label class="row">Tap zone width <input type="range" min="0.15" max="0.45" step="0.01" data-set="zone"></label>
      <label class="row"><input type="checkbox" data-set="swapZones"> Left side goes forward</label>
      <label class="row"><input type="checkbox" data-set="coverAlone"> First page alone in two-page view</label>
      <label class="row">Pages ready ahead <input type="number" min="1" max="12" data-set="ahead"></label>
      <div class="row buttons">
        ${scope === "comic" ? '<button data-act="forget-own">Use the settings for every comic</button>' : ""}
        <button data-act="restart">Mark as unread</button>
        <button data-act="close">Done</button>
      </div>`;
    const input = <T extends HTMLElement>(name: string) => sheet.querySelector<T>(`[data-set="${name}"]`)!;
    input<HTMLSelectElement>("scope").value = scope;
    input<HTMLSelectElement>("scope").onchange = (event) => { scope = (event.target as HTMLSelectElement).value as "comic" | "all"; };
    input<HTMLInputElement>("background").value = settings.background;
    input<HTMLInputElement>("background").onchange = (event) => change({ background: (event.target as HTMLInputElement).value });
    const padding = input<HTMLInputElement>("padding");
    const paddingShown = sheet.querySelector<HTMLElement>('[data-show="padding"]')!;
    padding.value = String(settings.padding);
    paddingShown.textContent = `${settings.padding}%`;
    // shown as it is dragged, saved when it is let go
    padding.oninput = () => {
      paddingShown.textContent = `${padding.value}%`;
      reader.style.setProperty("--pad", `${padding.value}vw`);
      scrolling?.look(settings.fit, Number(padding.value), settings.gap);
    };
    padding.onchange = () => change({ padding: Number(padding.value) });
    // space between pages when scrolling, so short strips do not run together: in pixels, shown as dragged
    const gap = input<HTMLInputElement>("gap");
    const gapShown = sheet.querySelector<HTMLElement>('[data-show="gap"]')!;
    gap.value = String(settings.gap);
    gapShown.textContent = `${settings.gap}px`;
    gap.oninput = () => {
      gapShown.textContent = `${gap.value}px`;
      scrolling?.look(settings.fit, settings.padding, Number(gap.value));
    };
    gap.onchange = () => change({ gap: Number(gap.value) });
    input<HTMLInputElement>("zone").value = String(settings.zone);
    input<HTMLInputElement>("zone").onchange = (event) => change({ zone: Number((event.target as HTMLInputElement).value) });
    input<HTMLInputElement>("swapZones").checked = settings.swapZones;
    input<HTMLInputElement>("swapZones").onchange = (event) => change({ swapZones: (event.target as HTMLInputElement).checked });
    input<HTMLInputElement>("coverAlone").checked = settings.coverAlone;
    input<HTMLInputElement>("coverAlone").onchange = (event) => change({ coverAlone: (event.target as HTMLInputElement).checked });
    input<HTMLInputElement>("ahead").value = String(settings.ahead);
    input<HTMLInputElement>("ahead").onchange = (event) => change({ ahead: Number((event.target as HTMLInputElement).value) });
    const forget = sheet.querySelector<HTMLButtonElement>('[data-act="forget-own"]');
    if (forget) forget.onclick = () => {
      own = {};
      scope = "all";
      api.saveComicSettings(comic.id, {}).catch(() => undefined);
      settings = merged(globalSettings, own);
      shown = views(comic.pages, settings, starts);
      view = viewOf(shown, page());
      render();
      openSheet();
    };
    // marked unread, the comic is closed: the place stops being kept first, or leaving it - or the next
    // scroll - would save it straight back
    sheet.querySelector<HTMLButtonElement>('[data-act="restart"]')!.onclick = async () => {
      keepingPlace = false;
      window.clearTimeout(saveTimer);
      saveTimer = undefined;
      await api.forgetProgress(comic.id).catch(() => undefined);
      leave();
    };
    sheet.querySelector<HTMLButtonElement>('[data-act="close"]')!.onclick = () => sheet.classList.add("hidden");
    sheet.addEventListener("pointerdown", (event) => event.stopPropagation());
    sheet.classList.remove("hidden");
  }

  // the page on screen as a cover: of this comic, or of the folder, series or author it is in. the first page
  // on screen, which in two pages side by side is the one read first
  function openCoverSheet() {
    const at = shown[view][0];
    const folderName = comic.place ? comic.place.split("/").pop()! : "";
    const targets: [target: string, label: string][] = [[`comic:${comic.id}`, "This comic"]];
    if (comic.place) targets.push([`folder:${comic.place}`, `The folder ${folderName}`]);
    if (comic.series) targets.push([`series:${comic.series}`, `The series ${comic.series}`]);
    if (comic.author) targets.push([`author:${comic.author}`, `The author ${comic.author}`]);
    sheet.innerHTML = `
      <h2>Page ${at + 1} as the cover of</h2>
      ${targets.map(([, label], n) => `<div class="row"><button data-target="${n}">${esc(label)}</button></div>`).join("")}
      <div class="row buttons"><button data-act="close">Cancel</button></div>`;
    sheet.querySelectorAll<HTMLButtonElement>("[data-target]").forEach((button) => {
      button.onclick = async () => {
        sheet.classList.add("hidden");
        try {
          notify(coverMessage(await api.chooseCover(targets[Number(button.dataset.target)][0], comic.id, at)));
        } catch (error) {
          notify(refusal(error));
        }
      };
    });
    sheet.querySelector<HTMLButtonElement>('[data-act="close"]')!.onclick = () => sheet.classList.add("hidden");
    sheet.addEventListener("pointerdown", (event) => event.stopPropagation());
    sheet.classList.remove("hidden");
  }

  // input: taps, swipes and pinches on the stage; keys and a page-turner anywhere; the wheel at a page's end
  const detach = attachGestures(stage, {
    tap(x) {
      if (!sheet.classList.contains("hidden")) return sheet.classList.add("hidden");
      const action = tapAction(x, stage.clientWidth, settings);
      if (action === "menu") return toggleMenu();
      if (!menu.classList.contains("hidden")) return toggleMenu(false);
      turn(action === "forward");
    },
    doubleTap(x, y) {
      if (zoom.scale > 1.01) return resetZoom();
      zoomTo(2.5, x, y);
    },
    swipe(direction) {
      const forward = (direction === "left") !== (settings.direction === "rtl");
      turn(forward);
    },
    drag(dx, dy) {
      stage.scrollBy({ left: -dx, top: -dy });
    },
    zoom(scale, originX, originY, panX, panY) {
      if (scale !== zoom.scale && originX) zoomTo(scale, originX, originY);
      zoom.x += panX;
      zoom.y += panY;
      paintZoom();
    },
    scale: () => zoom.scale,
    middle: (x) => tapAction(x, stage.clientWidth, settings) === "menu",
  });

  function zoomTo(scale: number, x: number, y: number) {
    // the point under the fingers stays under them: the spread's own corner is where scaling is measured from
    const box = spread.getBoundingClientRect();
    const originX = box.left - zoom.x;
    const originY = box.top - zoom.y;
    const k = scale / zoom.scale;
    zoom.x = (x - originX) - ((x - originX) - zoom.x) * k;
    zoom.y = (y - originY) - ((y - originY) - zoom.y) * k;
    zoom.scale = scale;
    if (scale <= 1.01) return resetZoom();
    paintZoom();
  }

  function paintZoom() {
    spread.style.transform = zoom.scale > 1.01 ? `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})` : "";
  }

  strip.addEventListener("click", (event) => {
    // a click on a video or a flash movie is its own - a flash comic's own next button among them
    if ((event.target as Element).closest?.(".embed")) return;
    const action = tapAction(event.clientX, strip.clientWidth, settings);
    if (action === "menu") toggleMenu();
    else turn(action === "forward");
  });

  const keys = (event: KeyboardEvent) => {
    if ((event.target as HTMLElement).closest("input, select, textarea")) return;
    // a flash movie played with the keyboard keeps its keys while it has them
    if ((event.target as Element).closest?.(".embed") || document.activeElement?.closest(".embed")) return;
    if (event.key === "f") return toggleFullscreen();
    const action = keyAction(event.key, event.shiftKey, settings.direction);
    if (!action) return;
    event.preventDefault();
    if (action === "menu") return event.key === "Escape" && menu.classList.contains("hidden") ? (save(), leave()) : toggleMenu();
    if (action === "first") return go(0);
    if (action === "last") return go(comic.pages.length - 1);
    if (action === "ahead" || action === "behind") return jumpBy(action === "ahead" ? 10 : -10);
    if (action === "nextChapter" || action === "previousChapter") return jumpChapter(action === "nextChapter");
    if (action === "up" || action === "down") return nudge(action === "down" ? 1 : -1);
    turn(action === "forward");
  };

  // a small move, for putting a page just where it reads best, never for turning it. it eases there as a
  // mouse wheel's smooth scrolling does, rather than jumping: each press moves where the page is headed,
  // and the page closes on it a share of the way each frame - so a key held down, repeating, glides, and
  // slows to a stop when let go. a zoomed page is moved within its zoom instead
  let glide: { scroller: HTMLElement; target: number; frame: number } | null = null;

  function nudge(way: number) {
    if (settings.mode !== "webtoon" && zoom.scale > 1.01) {
      zoom.y -= way * Math.max(40, stage.clientHeight * 0.08);
      paintZoom();
      return;
    }
    const scroller = settings.mode === "webtoon" ? strip : stage;
    glideBy(scroller, way * Math.max(40, scroller.clientHeight * 0.08));
  }

  // where a scroller is headed: where a glide under way will end, or where it is
  function headedTo(scroller: HTMLElement): number {
    return glide && glide.scroller === scroller ? glide.target : scroller.scrollTop;
  }

  // move a scroller by `distance`, easing there: a nudge, or a whole page turned in scroll mode. a press
  // during a glide carries on from where it was headed, so presses in a row add up rather than restarting
  function glideBy(scroller: HTMLElement, distance: number) {
    const furthest = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    const target = clamp(headedTo(scroller) + distance, 0, furthest);
    if (glide && glide.scroller === scroller) {
      glide.target = target;
      return;
    }
    stopGlide();
    glide = { scroller, target, frame: requestAnimationFrame(glideOn) };
  }

  function glideOn() {
    if (!glide) return;
    const { scroller, target } = glide;
    const left = target - scroller.scrollTop;
    if (Math.abs(left) < 1) {
      scroller.scrollTop = target;
      glide = null;
      return;
    }
    const was = scroller.scrollTop;
    // at least a pixel a frame, or a page whose scroll is kept to whole pixels would never arrive
    scroller.scrollTop = was + Math.sign(left) * Math.max(1, Math.abs(left) * 0.2);
    if (scroller.scrollTop === was) {
      glide = null;
      return;
    }
    glide.frame = requestAnimationFrame(glideOn);
  }

  // a wheel or a finger takes over from a glide under way, rather than being pulled back toward it
  function stopGlide() {
    if (glide) cancelAnimationFrame(glide.frame);
    glide = null;
  }
  strip.addEventListener("wheel", stopGlide, { passive: true });
  strip.addEventListener("touchstart", stopGlide, { passive: true });
  stage.addEventListener("touchstart", stopGlide, { passive: true });
  window.addEventListener("keydown", keys);

  let wheelAt = 0;
  const wheel = (event: WheelEvent) => {
    stopGlide();
    if (settings.mode === "webtoon" || event.ctrlKey) return;
    const vertical = stage.scrollHeight - stage.clientHeight > 4;
    if (vertical && !(event.deltaY > 0 ? stage.scrollTop + stage.clientHeight >= stage.scrollHeight - 4 : stage.scrollTop <= 4)) return;
    event.preventDefault();
    const now = performance.now();
    if (now - wheelAt < 350) return;
    wheelAt = now;
    turn(event.deltaY > 0);
  };
  stage.addEventListener("wheel", wheel, { passive: false });

  // the window closed, or the app switched away from on a phone: the place as it is this moment
  const hidden = () => { if (document.visibilityState === "hidden") save(true); };
  const closing = () => save(true);
  document.addEventListener("visibilitychange", hidden);
  window.addEventListener("pagehide", closing);

  buildMenu();
  render();
  if (startAt === null && comic.position > 0 && comic.position >= comic.seen - 1 && comic.pages.length > comic.seen) {
    notify(`${comic.pages.length - comic.seen} new since you last read`);
  }

  return () => {
    window.clearTimeout(saveTimer);
    save(true);
    detach();
    clearStrip();
    window.removeEventListener("keydown", keys);
    document.removeEventListener("visibilitychange", hidden);
    window.removeEventListener("pagehide", closing);
    stage.removeEventListener("wheel", wheel);
    stopGlide();
  };
}
