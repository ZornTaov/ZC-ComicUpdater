// three screens, chosen by the address: #/browse/<how>/<where> is the library, #/read/<comic>[/<page>] a comic
// open for reading, and #/info/<comic> what a comic is and where it came from, so the back button and a
// bookmark all do what they should
import "./style.css";
import { esc } from "./dom";
import { openInfo } from "./info";
import { browseHash, openLibrary, rememberedBrowse } from "./library";
import { openReader } from "./reader";
import type { Browse } from "./shelves";

const root = document.getElementById("app")!;
let close: () => void = () => undefined;
// where the library was when a comic was opened, so closing it goes back there rather than to the top
let lastBrowse = "";
// whether anything was shown before this screen: an info page opened from a bookmark has nowhere to go back
// to in this page's history, and goes to the library instead
let shownBefore = false;

async function route() {
  close();
  close = () => undefined;
  const reading = location.hash.match(/^#\/read\/([0-9a-f]+)(?:\/(\d+))?/);
  const browsing = location.hash.match(/^#\/browse\/(folder|series|author|all)(?:\/(.*))?$/);
  const about = location.hash.match(/^#\/info\/([0-9a-f]+)/);
  const cameFrom = shownBefore;
  shownBefore = true;
  try {
    if (about) {
      document.body.classList.remove("reading");
      close = await openInfo(root, about[1], () => {
        if (cameFrom) history.back();
        else location.hash = lastBrowse || browseHash(rememberedBrowse());
      });
    } else if (reading) {
      document.body.classList.add("reading");
      close = await openReader(root, reading[1], reading[2] !== undefined ? Number(reading[2]) - 1 : null,
                               () => { location.hash = lastBrowse || browseHash(rememberedBrowse()); });
      // a page in the address is where to open, once: coming back to it - from the info page - opens the
      // comic where it was left, not on that page again
      if (reading[2] !== undefined) history.replaceState(null, "", `#/read/${reading[1]}`);
    } else if (browsing) {
      document.body.classList.remove("reading");
      lastBrowse = location.hash;
      close = await openLibrary(root, browsing[1] as Browse, browsing[2] ? decodeURIComponent(browsing[2]) : "",
                                (id, at) => { location.hash = at === null ? `#/read/${id}` : `#/read/${id}/${at + 1}`; });
    } else {
      location.replace(browseHash(rememberedBrowse()));
    }
  } catch (error) {
    root.innerHTML = `<p class="empty">Something went wrong: ${esc(String(error))}. <a href="#/">Back to the library</a></p>`;
  }
}

window.addEventListener("hashchange", route);
route();
