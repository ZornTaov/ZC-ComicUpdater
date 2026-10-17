//what every other part of the page leans on: finding an element, reaching the server, and putting text
//and times on screen. these are plain scripts sharing one global scope rather than modules, so a dialog
//can set the comic the editor holds without an import to route it through. index.html loads them in
//order, and only main.js calls anything as it loads, so each file may use what a later one declares

const $ = (id) => document.getElementById(id);
// requests go to the bare origin: an address with a password typed into it makes the browser refuse relative ones
const api = (path) => location.origin + path;

function esc(text) {
  return String(text ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function clock(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds / 60) % 60, s = seconds % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
}
function when(stamp) {
  if (!stamp) return "";
  const d = typeof stamp === "number" ? new Date(stamp * 1000) : new Date(stamp);
  if (isNaN(d)) return String(stamp);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
async function post(path, body) {
  const response = await fetch(api(path), { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

//a dialog closed by a click beside it, but only one pressed and let go both outside its box: a drag that
//selects a field's text and is let go past the dialog's edge ends in a click on the dialog too, and must
//not throw away what was being edited
function closeOnBackdrop(dialog) {
  let pressedOutside = false;
  const outside = (event) => {
    const box = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom);
  };
  dialog.addEventListener("pointerdown", (event) => { pressedOutside = outside(event); });
  dialog.addEventListener("click", (event) => {
    if (pressedOutside && outside(event)) dialog.close();
    pressedOutside = false;
  });
}

function link(url) {
  return url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a>` : `<span class="muted">none</span>`;
}
//everything one comic said during one update, opened as plain text in a tab of its own
function logLink(name, text) {
  return `<a class="log-link" href="${esc(api("/api/log?name=" + encodeURIComponent(name)))}" target="_blank"
    rel="noreferrer">${esc(text || "log")}</a>`;
}
