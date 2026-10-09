// two screens, chosen by the address: #/ is the library, #/read/<comic>[/<page>] a comic open for reading,
// so the back button and a bookmark both do what they should
import "./style.css";
import { esc } from "./dom";
import { openLibrary } from "./library";
import { openReader } from "./reader";

const root = document.getElementById("app")!;
let close: () => void = () => undefined;

async function route() {
  close();
  close = () => undefined;
  const reading = location.hash.match(/^#\/read\/([0-9a-f]+)(?:\/(\d+))?/);
  try {
    if (reading) {
      document.body.classList.add("reading");
      close = await openReader(root, reading[1], reading[2] !== undefined ? Number(reading[2]) - 1 : null,
                               () => { location.hash = "#/"; });
    } else {
      document.body.classList.remove("reading");
      close = await openLibrary(root, (id, at) => {
        location.hash = at === null ? `#/read/${id}` : `#/read/${id}/${at + 1}`;
      });
    }
  } catch (error) {
    root.innerHTML = `<p class="empty">Something went wrong: ${esc(String(error))}. <a href="#/">Back to the library</a></p>`;
  }
}

window.addEventListener("hashchange", route);
route();
