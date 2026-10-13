//the editor a comic's Edit button opens: its settings, what its runs have said, and working out its
//chapters

const flags = ["prefix", "javascript", "firefox", "cbz", "direction_check", "multi_page", "ended"];
//the ones a comic has unless it says otherwise, so a file written before the setting existed shows the
//behaviour it actually gets rather than an unticked box
const onByDefault = ["cbz", "direction_check", "multi_page"];
let editing = null;
//the chapters job the editor queued, watched by running.js so that if it stops to ask, the question is
//put here while the editor is still open
let chapterJob = null;


async function openEditor(name) {
  const msg = $("edit-msg");
  msg.className = "msg"; msg.textContent = "";
  let detail;
  try {
    const response = await fetch(api(`/api/comic?name=${encodeURIComponent(name)}`));
    detail = await response.json();
    if (!response.ok) throw new Error(detail.error || response.statusText);
  } catch (error) {
    alert("Could not open " + name + ": " + error.message);
    return;
  }
  editing = detail;
  const s = detail.settings, st = detail.state, last = detail.runs[0] || {};
  $("edit-name").textContent = detail.name;
  $("edit-updated").textContent = detail.updated ? "saved " + when(detail.updated) : "";
  $("edit-facts").innerHTML = `
    <dt>Pages held</dt><dd>${detail.pages_in_folder}${st.page_count != null && st.page_count !== detail.pages_in_folder ? ` (metadata says ${st.page_count})` : ""}</dd>
    <dt>Last saved file</dt><dd>${esc(st.last_image_file || "") || '<span class="muted">none</span>'}</dd>
    <dt>Last run ended</dt><dd>${last.stop_reason ? esc(last.stop_reason) + (last.exit_code ? ` (exit ${last.exit_code})` : "") + " at " + link(last.last_url) : '<span class="muted">never run</span>'}</dd>
    <dt>First page</dt><dd>${link(detail.first_page_url)}</dd>
    ${perAddress(s, st)}`;
  $("e-url").value = s.url || "";
  $("e-url-hints").innerHTML = s.url ? ` <a href="${esc(s.url)}" target="_blank" rel="noreferrer" class="link">open it</a>` : "";
  $("e-increment").value = s.increment ?? "";
  $("e-cbz_path").value = s.cbz_path || "";
  $("e-waittime").value = s.waittime || 0;
  const chapters = detail.chapters || {};
  $("e-chapters").value = chapters.source_url || "";
  $("e-every").value = chapters.every || "";
  //an archive page is one source of chapters and the comic's own addresses are another: a comic that
  //counts /comic/issue-4-page-7 often reads better from those than from an archive with no headings
  const from = chapters.source === "every" && chapters.every ? `cutting it every ${chapters.every} pages`
    : chapters.source === "archive" && chapters.source_url ? "that page" : "the comic's own addresses";
  $("e-chapters-note").textContent = (chapters.count
    ? `${chapters.count} chapter(s) worked out from ${from}${chapters.packed ? ", archives written " + when(chapters.packed) : ""}. `
    : detail.stale_walk ? `A walk that never got past ${detail.indexed_pages} page(s) is recorded for it, which says nothing about which page is which. `
    : detail.indexed_pages > 1 ? `Which page is which is known for ${detail.indexed_pages} page(s); the walk carries on from there. `
    : "Working these out walks the comic once, downloading nothing. It can take a few minutes. ")
    + "Leave it blank to read the chapters out of the comic's own page addresses instead.";
  $("e-discard-walk").hidden = !detail.stale_walk;
  //a comic another program scrapes has its plugin's settings, and none of the built-in scraper's
  const plugin = detail.plugin;
  $("editor").classList.toggle("with-plugin", !!plugin);
  if (plugin && !plugin.error) {
    $("e-plugin-note").textContent = `${plugin.title}'s settings. Its chapters come from it, as it fetches them.`;
    drawPluginForm($("e-plugin"), plugin, pluginValues(s));
  } else {
    clearPluginForm($("e-plugin"));
    $("e-plugin-note").textContent = plugin ? plugin.error : "";
  }
  showDecision(detail.decide);
  flags.forEach((key) => { $("e-" + key).checked = onByDefault.includes(key) ? s[key] !== false : !!s[key]; });
  const next = detail.pages_in_folder + 1;
  $("e-next-number").textContent = `use ${next}, the number after the pages held`;
  $("e-next-number").onclick = () => { $("e-increment").value = next; };

  const runs = detail.runs.map((r) => `<tr><td>${esc(when(r.started))}</td><td class="num">${r.pages_saved ?? ""}</td>
    <td>${esc(r.stop_reason || "")}${r.exit_code ? " (exit " + r.exit_code + ")" : ""}</td>
    <td>${r.last_page_number ?? ""}</td><td>${link(r.last_url)}</td></tr>`).join("");
  const edits = detail.edits.map((e) => `<div class="history-item line">${esc(when(e.at))}: ${esc(Object.entries(e.changed)
    .map(([key, pair]) => `${key} ${JSON.stringify(pair[0])} → ${JSON.stringify(pair[1])}`).join(", "))}</div>`).join("");
  //a week of its updates, each one's output in full, newest first - an update that found nothing new is here too
  const logs = (detail.logs || []).map((l) => logLink(l.name, when(l.at))).join(" · ");
  $("edit-runs").innerHTML = (runs ? `<div class="table-wrap" style="max-height:none"><table class="runs"><thead><tr><th>Started</th>
    <th>Saved</th><th>Ended</th><th>At #</th><th>Last page</th></tr></thead><tbody>${runs}</tbody></table></div>` : "") +
    (logs ? `<div class="muted" style="margin-top:10px">What each update said</div><div class="line">${logs}</div>` : "") +
    (edits ? `<div class="muted" style="margin-top:10px">Edits</div>${edits}` : "");
  $("edit-runs-box").hidden = !runs && !edits && !logs;

  $("e-move-into").value = parentOf(detail.name);
  showPlaces(movePlaces(detail.name));
  placesAsked = false;
  $("edit-move-box").open = false;
  resetMove();

  const busy = detail.running || detail.moving;
  ["edit-save", "edit-save-update", "e-move-check"].forEach((id) => { $(id).disabled = busy; });
  if (busy) {
    msg.className = "msg bad";
    msg.textContent = detail.moving ? "Waiting to be moved; reopen it once the move has finished."
      : "Being scraped right now; stop it or wait to edit.";
  }
  $("editor").showModal();
}

//the folder a comic sits in, by its name in the library
function parentOf(name) {
  return name.includes("/") ? name.slice(0, name.lastIndexOf("/")) : "";
}

//the folders a comic could be moved into that the page knows already: every folder another comic sits in,
//and the ones above those. shown at once, while the folders that hold no comic yet are asked for
function movePlaces(name, more = []) {
  const places = new Set(more);
  comics.forEach((comic) => {
    const parts = comic.name.split("/").slice(0, -1);
    parts.forEach((_, at) => places.add(parts.slice(0, at + 1).join("/")));
  });
  places.delete(parentOf(name));
  return [...places].sort((a, b) => a.localeCompare(b));
}

function showPlaces(places) {
  $("e-move-places").innerHTML = places.map((place) => `<option value="${esc(place)}">`).join("");
}

//every folder under the pages folder, an author's holding nothing tracked yet among them. asked once a
//dialog, when the move is opened, since it is a look through the library's folders
let placesAsked = false;
$("edit-move-box").addEventListener("toggle", async () => {
  if (!$("edit-move-box").open || placesAsked || !editing) return;
  placesAsked = true;
  const name = editing.name;
  try {
    const response = await fetch(api("/api/places"));
    const found = await response.json();
    if (!response.ok) throw new Error(found.error || response.statusText);
    if (editing && editing.name === name) showPlaces(movePlaces(name, found.places));
  } catch (error) {
    //the folders the comics are in are still offered, and any folder can be typed
    placesAsked = false;
  }
});

//the move button only ever does what was last shown, so a folder typed after looking has to be looked at
let moveChecked = null;
function resetMove() {
  moveChecked = null;
  $("e-move-plan").hidden = true;
  $("e-move-plan").innerHTML = "";
  $("e-move-go").disabled = true;
}

$("e-move-into").addEventListener("input", resetMove);
$("e-move-check").addEventListener("click", async () => {
  const msg = $("edit-msg"), into = $("e-move-into").value.trim();
  resetMove();
  msg.className = "msg"; msg.textContent = "Looking…";
  try {
    const result = await post("/api/move", { name: editing.name, into, dry_run: true });
    $("e-move-plan").innerHTML = result.lines.map((line) =>
      `<div class="${line.stays ? "stays" : ""}">${esc(line.text)}</div>`).join("");
    $("e-move-plan").hidden = false;
    $("e-move-go").disabled = false;
    moveChecked = into;
    msg.textContent = "";
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
$("e-move-go").addEventListener("click", async () => {
  const msg = $("edit-msg");
  if (moveChecked === null) return;
  try {
    const result = await post("/api/move", { name: editing.name, into: moveChecked });
    //the comic is about to have another name, so nothing more is saved under this one
    ["edit-save", "edit-save-update", "e-move-check", "e-move-go"].forEach((id) => { $(id).disabled = true; });
    msg.className = "msg good";
    msg.textContent = `Queued; it becomes ${result.to} when its turn comes. Watch it under Running now.`;
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});

async function saveEditor(updateAfter) {
  const msg = $("edit-msg");
  msg.className = "msg"; msg.textContent = "Saving…";
  //a plugin comic's address is one of its plugin's settings, and its chapters come from the plugin
  const settings = editing.plugin
    ? { cbz_path: $("e-cbz_path").value, plugin: readPluginForm($("e-plugin")) }
    : { url: $("e-url").value, increment: $("e-increment").value, cbz_path: $("e-cbz_path").value,
        waittime: $("e-waittime").value, chapters_url: $("e-chapters").value, chapters_every: $("e-every").value };
  flags.forEach((key) => { settings[key] = $("e-" + key).checked; });
  try {
    const result = await post("/api/settings", { name: editing.name, updated: editing.updated, settings, update_after: updateAfter });
    msg.className = "msg good";
    msg.textContent = (result.saved ? "Saved." : "Nothing changed.") + (result.queued ? " Update queued." : "");
    if (result.updated) editing.updated = result.updated;
    loadComics();
    if (updateAfter) setTimeout(() => $("editor").close(), 700);
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
}

function perAddress(settings, state) {
  //only worth a row when there is something to say: most comics put one page at one address and always
  //will, and a row saying "one" on every comic in the library teaches nothing
  const most = state.pages_per_url || 1;
  if (most < 2) return "";
  const since = state.multi_page_from ? `, first seen at ${link(state.multi_page_from)}` : "";
  //a comic serving several while told to read one is saving a fraction of itself, which is worth flagging
  //here rather than leaving to be noticed as a short page count
  const off = settings.multi_page === false
    ? ` <span class="s-stopped">— but this comic is set to read one an address, so the rest are skipped</span>` : "";
  return `<dt>Pages an address</dt><dd>up to ${most}${since}${off}</dd>`;
}

$("edit-chapterize").addEventListener("click", async () => {
  const msg = $("edit-msg");
  msg.className = "msg";
  msg.textContent = "Saving the chapter list first…";
  try {
    await saveEditor(false);
    const result = await post("/api/chapterize", { name: editing.name, url: $("e-chapters").value.trim(),
                                                    every: $("e-every").value.trim() });
    chapterJob = { id: result.queued, name: editing.name };
    showDecision(null);
    msg.className = "msg good";
    msg.textContent = (result.from === "addresses" ? "Queued, reading the comic's own addresses. "
      : result.from === "every" ? `Queued, cutting it every ${$("e-every").value.trim()} pages. ` : "Queued. ")
      + (result.numbers_first ? "Where every file carries its page number it is cut from those; otherwise it stops and asks here what to do. Watch it under Running now."
        : result.carrying_on ? "The record of which page is which stops short of the newest page, so the walk carries on from where it stopped; watch it under Running now."
        : result.walking ? "It walks the comic first, which takes a few minutes; watch it under Running now."
        : "Watch it under Running now.");
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
function showDecision(decide) {
  //why cutting by the file numbers stopped before it did anything, and the ways on from there. nothing
  //is chosen for the reader where the copies differ: only they can say which one is the page
  const box = $("edit-decide");
  box.hidden = !decide;
  if (!decide) { box.innerHTML = ""; return; }
  const twice = decide.twice || [], stale = decide.stale_walk, unnumbered = decide.unnumbered || [];
  const kb = (bytes) => `${Math.round(bytes / 1024).toLocaleString()} KB`;
  const groups = twice.map((group, at) => `<fieldset class="decide-group" data-page="${group.page}">
    <legend>Page ${group.page} is on ${group.files.length} files${group.identical ? ", the same image each time" : ", and they differ"}: keep</legend>
    ${group.files.map((file, which) => `<label class="check"><input type="radio" name="keep-${at}" value="${esc(file.name)}"
      ${group.identical && which === 0 ? "checked" : ""}> ${esc(file.name)} <span class="muted">${kb(file.bytes)}</span></label>`).join("")}
  </fieldset>`).join("");
  const fix = twice.length && stale ? "Set the others aside, discard that walk, and cut"
    : twice.length ? "Set the others aside and cut" : stale ? "Discard that walk and cut" : "";
  box.innerHTML = `<div class="decide-why">Stopped before walking or changing anything: ${esc(decide.why)}.</div>
    ${groups}
    ${twice.length ? `<div class="note">The file not kept is moved into the comic's <code>.set aside</code> folder, not deleted, and goes in no archive.</div>` : ""}
    ${stale ? `<div class="note">The walk recorded for it (${esc(stale.file)}, ${stale.pages} page(s)) is renamed aside in the config folder, not deleted.</div>` : ""}
    ${unnumbered.length ? `<div class="note">${decide.unnumbered_count} file(s) carry no page number, such as ${unnumbered.slice(0, 5).map(esc).join(", ")}.
      Only a walk can say where those go.</div>` : ""}
    <div class="row">
      ${fix && !unnumbered.length ? `<button type="button" class="primary" id="decide-go">${fix}</button>` : ""}
      <button type="button" id="decide-walk">Walk it instead</button>
      <span class="note">A walk loads every page of the comic, which can take an hour.</span>
    </div>`;
  box.dataset.every = decide.every || "";
  box.dataset.stale = stale ? "1" : "";
}

async function decideAndRun(walk) {
  const box = $("edit-decide"), msg = $("edit-msg");
  const setAside = [];
  if (!walk) {
    for (const group of box.querySelectorAll(".decide-group")) {
      const kept = group.querySelector("input:checked");
      if (!kept) {
        msg.className = "msg bad";
        msg.textContent = `Choose which file to keep for page ${group.dataset.page}.`;
        return;
      }
      group.querySelectorAll("input").forEach((input) => { if (input !== kept) setAside.push(input.value); });
    }
  }
  try {
    const result = await post("/api/chapterize", { name: editing.name, url: "", every: box.dataset.every,
      set_aside: setAside, discard_walk: !!box.dataset.stale, walk });
    chapterJob = { id: result.queued, name: editing.name };
    showDecision(null);
    msg.className = "msg good";
    msg.textContent = walk ? "Queued, walking it first; watch it under Running now."
      : "Queued, with what you chose done first; watch it under Running now.";
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
}

$("edit-decide").addEventListener("click", (event) => {
  if (event.target.id === "decide-go") decideAndRun(false);
  else if (event.target.id === "decide-walk") decideAndRun(true);
});
$("e-discard-walk").addEventListener("click", async () => {
  const msg = $("edit-msg");
  if (!confirm("Discard the walk recorded for this comic? Its files are renamed aside in the config folder, not deleted.")) return;
  try {
    const result = await post("/api/discardwalk", { name: editing.name });
    msg.className = "msg good";
    msg.textContent = `Moved aside: ${result.moved.join(", ")}.`;
    $("e-discard-walk").hidden = true;
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
$("edit-save").addEventListener("click", () => saveEditor(false));
$("edit-save-update").addEventListener("click", () => saveEditor(true));
$("edit-cancel").addEventListener("click", () => $("editor").close());
