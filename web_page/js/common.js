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

function link(url) {
  return url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a>` : `<span class="muted">none</span>`;
}
