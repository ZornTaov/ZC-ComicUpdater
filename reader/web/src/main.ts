// two screens, chosen by the address: #/browse/<how>/<where> is the library, #/read/<comic>[/<page>] a comic
// open for reading, so the back button and a bookmark both do what they should
import "./style.css";
import { esc } from "./dom";
import { browseHash, openLibrary, rememberedBrowse } from "./library";
import { openReader } from "./reader";
import type { Browse } from "./shelves";

const root = document.getElementById("app")!;
let close: () => void = () => undefined;
// where the library was when a comic was opened, so closing it goes back there rather than to the top
let lastBrowse = "";

async function route() {
  close();
  close = () => undefined;
  const reading = location.hash.match(/^#\/read\/([0-9a-f]+)(?:\/(\d+))?/);
  const browsing = location.hash.match(/^#\/browse\/(folder|series|author|all)(?:\/(.*))?$/);
  try {
    if (reading) {
      document.body.classList.add("reading");
      close = await openReader(root, reading[1], reading[2] !== undefined ? Number(reading[2]) - 1 : null,
                               () => { location.hash = lastBrowse || browseHash(rememberedBrowse()); });
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
