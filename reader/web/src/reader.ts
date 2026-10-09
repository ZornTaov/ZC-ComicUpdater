// a comic open for reading: the page or pages on screen, the ones either side already decoded so a turn is
// instant, and the menu a tap in the middle brings up. where the reader is up to goes to the server as it
// changes, by page rather than by number, so it survives the comic growing or being renumbered.
import { api, type StandIn } from "./api";
import { attachGestures } from "./gestures";
import { chapterOf, keyAction, tapAction, viewOf, views, wanted } from "./layout";
import { Strip } from "./strip";
import { clean, merged, type Settings } from "./settings";
import { el, esc } from "./dom";
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
  let lastSaved = -1;

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
      });
    }
    scrolling.look(settings.fit, settings.padding);
    scrolling.jumpTo(page());
    updateMenu();
  }

  // leaving scrolling: every player stopped, every picture let go
  function clearStrip() {
    scrolling?.destroy();
    scrolling = null;
  }

  function remember() {
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(save, 600);
  }

  function save() {
    const at = page();
    if (at === lastSaved) return;
    lastSaved = at;
    api.saveProgress(comic.id, at).catch(() => { lastSaved = -1; });
  }

  // a page taller than the screen is read down before it is turned, as a reader of a printed page reads
  // to the bottom of it; only then does forward turn
  function scrolledThrough(forward: boolean): boolean {
    const vertical = stage.scrollHeight - stage.clientHeight > 4;
    const horizontal = stage.scrollWidth - stage.clientWidth > 4;
    if (vertical) {
      const atEnd = forward ? stage.scrollTop + stage.clientHeight >= stage.scrollHeight - 4 : stage.scrollTop <= 4;
      if (!atEnd) {
        stage.scrollBy({ top: (forward ? 1 : -1) * stage.clientHeight * 0.85 });
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
      strip.scrollBy({ top: (forward ? 1 : -1) * strip.clientHeight * 0.85 });
      return;
    }
    if (zoom.scale > 1.01) {
      resetZoom();
      return;
    }
    if (!scrolledThrough(forward)) return;
    const next = view + (forward ? 1 : -1);
    if (next < 0) return notify("This is the first page");
    if (next >= shown.length) return notify(comic.ended ? "The end" : "You're up to date");
    view = next;
    render();
  }

  function go(n: number) {
    view = viewOf(shown, clamp(n, 0, comic.pages.length - 1));
    render();
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
      </header>
      <footer>
        <div class="slider-row">
          <span class="where"></span>
          <input type="range" min="0" max="${comic.pages.length - 1}" step="1" data-act="slider">
        </div>
        <div class="buttons">
          <button data-act="mode"></button>
          <button data-act="direction"></button>
          <button data-act="fit"></button>
          <button data-act="fullscreen">Full screen</button>
          <button data-act="more">More…</button>
        </div>
      </footer>`;
    menu.querySelector<HTMLButtonElement>('[data-act="back"]')!.onclick = () => { save(); leave(); };
    const chapterSelect = menu.querySelector<HTMLSelectElement>('[data-act="chapter"]');
    if (chapterSelect) chapterSelect.onchange = () => { go(comic.chapters[Number(chapterSelect.value)].start); };
    const slider = menu.querySelector<HTMLInputElement>('[data-act="slider"]')!;
    slider.oninput = () => { menu.querySelector(".where")!.textContent = `${Number(slider.value) + 1} / ${comic.pages.length}`; };
    slider.onchange = () => go(Number(slider.value));
    const cycle = <K extends keyof Settings>(key: K, values: Settings[K][]) => () => {
      const now = values.indexOf(settings[key]);
      change({ [key]: values[(now + 1) % values.length] } as Partial<Settings>);
    };
    menu.querySelector<HTMLButtonElement>('[data-act="mode"]')!.onclick = cycle("mode", ["single", "spread", "webtoon"]);
    menu.querySelector<HTMLButtonElement>('[data-act="direction"]')!.onclick = cycle("direction", ["ltr", "rtl"]);
    menu.querySelector<HTMLButtonElement>('[data-act="fit"]')!.onclick = cycle("fit", ["screen", "width", "height", "original"]);
    menu.querySelector<HTMLButtonElement>('[data-act="fullscreen"]')!.onclick = toggleFullscreen;
    menu.querySelector<HTMLButtonElement>('[data-act="more"]')!.onclick = openSheet;
    menu.addEventListener("pointerdown", (event) => event.stopPropagation());
  }

  function updateMenu() {
    if (menu.classList.contains("hidden")) return;
    const at = page();
    const slider = menu.querySelector<HTMLInputElement>('[data-act="slider"]');
    if (slider) slider.value = String(at);
    const where = menu.querySelector(".where");
    if (where) where.textContent = `${at + 1} / ${comic.pages.length}`;
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
      scrolling?.look(settings.fit, Number(padding.value));
    };
    padding.onchange = () => change({ padding: Number(padding.value) });
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
    sheet.querySelector<HTMLButtonElement>('[data-act="restart"]')!.onclick = () => {
      api.forgetProgress(comic.id).then(() => notify("Marked as unread")).catch(() => undefined);
      lastSaved = -1;
      window.clearTimeout(saveTimer);
    };
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
    const action = tapAction(event.clientX, strip.clientWidth, settings);
    if (action === "menu") toggleMenu();
    else turn(action === "forward");
  });

  const keys = (event: KeyboardEvent) => {
    if ((event.target as HTMLElement).closest("input, select, textarea")) return;
    if (event.key === "f") return toggleFullscreen();
    const action = keyAction(event.key, event.shiftKey, settings.direction);
    if (!action) return;
    event.preventDefault();
    if (action === "menu") return event.key === "Escape" && menu.classList.contains("hidden") ? (save(), leave()) : toggleMenu();
    if (action === "first") return go(0);
    if (action === "last") return go(comic.pages.length - 1);
    turn(action === "forward");
  };
  window.addEventListener("keydown", keys);

  let wheelAt = 0;
  const wheel = (event: WheelEvent) => {
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

  const hidden = () => { if (document.visibilityState === "hidden") save(); };
  document.addEventListener("visibilitychange", hidden);

  buildMenu();
  render();
  if (startAt === null && comic.position > 0 && comic.position >= comic.seen - 1 && comic.pages.length > comic.seen) {
    notify(`${comic.pages.length - comic.seen} new since you last read`);
  }

  return () => {
    save();
    detach();
    clearStrip();
    window.removeEventListener("keydown", keys);
    document.removeEventListener("visibilitychange", hidden);
    stage.removeEventListener("wheel", wheel);
  };
}
