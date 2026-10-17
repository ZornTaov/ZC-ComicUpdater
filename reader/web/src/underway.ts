// a ComicInfo edit still being written, as a bar along the foot of every screen. one comic in a hundred chapter
// archives takes minutes, and the page that started it showed only "Writing…" all that while - or nothing at
// all, once it was closed or the page reloaded. asked for only while something is being written, never idly
import { api, type Underway } from "./api";
import { el, esc } from "./dom";

const EVERY = 1000;

let bar: HTMLElement | null = null;
let looking = false;
// saves sent and not yet answered
let waiting = 0;

// what the bar says: what is being written, how far it has got, and for how long
export function underwayText(now: Underway): string {
  const spent = now.seconds < 60 ? `${Math.floor(now.seconds)}s`
    : `${Math.floor(now.seconds / 60)}m ${String(Math.floor(now.seconds % 60)).padStart(2, "0")}s`;
  if (!now.total) return `Checking ${now.what} before writing its ComicInfo… ${spent}`;
  return `Writing ComicInfo of ${now.what}: ${now.done} of ${now.total} archive${now.total === 1 ? "" : "s"}, ${spent}`;
}

function draw(now: Underway | null) {
  if (!now) {
    bar?.remove();
    bar = null;
    return;
  }
  if (!bar) {
    bar = el("div", "underway");
    bar.setAttribute("role", "status");
    document.body.append(bar);
  }
  // no value while it is still being checked: a bar that moves without saying how far
  const value = now.total ? ` value="${now.done}" max="${now.total}"` : "";
  bar.innerHTML = `<progress${value}></progress>
    <span class="underway-text">${esc(underwayText(now))}</span>
    ${now.at ? `<span class="underway-at">${esc(now.at)}</span>` : ""}`;
}

// shows the bar for as long as an edit is being written: from the moment `saving` is sent - the server may not
// have begun it by the first look - until it is answered and the server says nothing is being written.
// called with nothing, it looks once, for an edit begun before the page was opened
export function watchUnderway(saving?: Promise<unknown>): void {
  if (saving) {
    waiting += 1;
    const answered = () => { waiting -= 1; };
    saving.then(answered, answered);
  }
  if (looking) return;
  looking = true;
  const look = async () => {
    let now: Underway | null = null;
    try {
      now = (await api.underway()).underway;
    } catch {
      // a reader too old to say, or not answering just now: the save's own answer still says how it went
      now = null;
    }
    draw(now);
    if (now || waiting > 0) {
      setTimeout(look, EVERY);
    } else {
      looking = false;
    }
  };
  void look();
}
