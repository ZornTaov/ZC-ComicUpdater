//the Library list: filtering it the way update_comics reads a glob, sorting it, ticking comics, and
//queueing their updates

let comics = [], sortKey = "name", sortDir = 1;
const checked = new Set();

// a glob the way update_comics reads one: * crosses folders, and a bare name matches a comic's own folder
function globTest(pattern) {
  pattern = pattern.trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  if (!pattern) return () => true;
  if (!/[*?[]/.test(pattern)) {
    const lower = pattern.toLowerCase();
    return (name) => name.toLowerCase().includes(lower);
  }
  const source = pattern.replace(/[.+^${}()|\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  const re = new RegExp("^" + source + "$", "i");
  return (name) => re.test(name) || re.test(name.split("/").pop());
}

function shownComics() {
  const test = globTest($("filter").value);
  const ended = $("show-ended").checked;
  return comics.filter((c) => (ended || !c.ended) && test(c.name)).sort((a, b) => {
    const x = a[sortKey] ?? "", y = b[sortKey] ?? "";
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sortDir;
  });
}

function renderComics() {
  const shown = shownComics();
  const rows = shown.map((c) => {
    //a run can end cleanly without having reached the end of the comic: priming saves one page on
    //purpose. "up to date" is only true when the last run followed the comic to where it stops.
    const waiting = c.exit_code === 0 && c.completed === false;
    const result = c.problem ? c.problem : c.ended ? "ended"
      : c.exit_code === null || c.exit_code === undefined ? (c.stop_reason || "")
      : !waiting && c.exit_code === 0 ? "up to date"
      : c.exit_code === 0 ? (c.stop_reason === "primed" ? "primed, waiting for its first update"
                                                        : `stopped early: ${c.stop_reason || "part way"}`)
      : `exit ${c.exit_code}: ${c.stop_reason || ""}`;
    const bad = c.problem || (c.exit_code && c.exit_code !== 0);
    return `<tr class="${c.ended ? "ended" : ""} ${c.problem ? "problem" : ""}">
      <td><input type="checkbox" data-name="${esc(c.name)}" ${checked.has(c.name) ? "checked" : ""} ${c.ended || c.problem ? "disabled" : ""}></td>
      <td class="name">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noreferrer" style="color:inherit">${esc(c.name)}</a>` : esc(c.name)}</td>
      <td class="num">${c.pages ?? ""}</td>
      <td class="muted wide-only" style="white-space:nowrap">${esc(when(c.updated))}</td>
      <td class="wide-only ${bad ? "s-failed" : waiting ? "s-waiting" : "muted"}">${esc(result)}</td>
      <td style="white-space:nowrap">${c.problem ? "" : `<button class="small" data-edit="${esc(c.name)}">Edit</button>`}
        ${c.ended || c.problem ? "" : `<button class="small" data-update="${esc(c.name)}">Update</button>`}</td>
    </tr>`;
  });
  $("comics").innerHTML = rows.join("") || `<tr><td colspan="6" class="empty">No comics match.</td></tr>`;
  const active = comics.filter((c) => !c.ended).length;
  const waiting = comics.filter((c) => !c.ended && c.exit_code === 0 && c.completed === false).length;
  $("count").textContent = `${shown.length} shown · ${active} active, ${comics.length - active} ended` +
    (waiting ? ` · ${waiting} with pages still to fetch` : "") +
    (checked.size ? ` · ${checked.size} checked` : "");
  $("update-checked").disabled = checked.size === 0;
  $("update-checked").textContent = checked.size ? `Update ${checked.size} checked` : "Update checked";
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.textContent = th.textContent.replace(/ [▲▼]$/, "") + (th.dataset.sort === sortKey ? (sortDir > 0 ? " ▲" : " ▼") : "");
  });
}

async function loadComics() {
  try {
    comics = await (await fetch(api("/api/comics"))).json();
    renderComics();
  } catch (error) {
    $("comics").innerHTML = `<tr><td colspan="6" class="s-failed">Could not read the library: ${esc(error.message)}</td></tr>`;
  }
}

async function queueUpdate(names) {
  try {
    await post("/api/update", { names });

  } catch (error) {
    alert("Could not start the update: " + error.message);
  }
}

$("comics").addEventListener("change", (event) => {
  const name = event.target.dataset.name;
  if (!name) return;
  event.target.checked ? checked.add(name) : checked.delete(name);
  renderComics();
});
$("comics").addEventListener("click", (event) => {
  const name = event.target.dataset.update;
  if (name) queueUpdate([name]);
  if (event.target.dataset.edit) openEditor(event.target.dataset.edit);
});

$("check-all").addEventListener("change", (event) => {
  shownComics().filter((c) => !c.ended && !c.problem).forEach((c) => event.target.checked ? checked.add(c.name) : checked.delete(c.name));
  renderComics();
});
$("update-checked").addEventListener("click", () => {
  queueUpdate([...checked]);
  checked.clear();
  $("check-all").checked = false;
  renderComics();
});
$("update-shown").addEventListener("click", () => {
  const filtering = $("filter").value.trim();
  const names = shownComics().filter((c) => !c.ended && !c.problem).map((c) => c.name);
  if (!names.length) return;
  if (!filtering && !confirm(`Update all ${names.length} active comics?`)) return;
  queueUpdate(filtering ? names : []);
});
$("filter").addEventListener("input", renderComics);
$("show-ended").addEventListener("change", renderComics);
$("reload").addEventListener("click", loadComics);
document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
  sortDir = sortKey === th.dataset.sort ? -sortDir : 1;
  sortKey = th.dataset.sort;
  renderComics();
}));
