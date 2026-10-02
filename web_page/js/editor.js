//the editor a comic's Edit button opens: its settings, what its runs have said, and working out its
//chapters

const flags = ["prefix", "javascript", "firefox", "cbz", "direction_check", "multi_page", "ended"];
//the ones a comic has unless it says otherwise, so a file written before the setting existed shows the
//behaviour it actually gets rather than an unticked box
const onByDefault = ["cbz", "direction_check", "multi_page"];
let editing = null;


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
    : detail.indexed_pages > 1 ? `Which page is which is known for ${detail.indexed_pages} page(s); the walk carries on from there. `
    : "Working these out walks the comic once, downloading nothing. It can take a few minutes. ")
    + "Leave it blank to read the chapters out of the comic's own page addresses instead.";
  flags.forEach((key) => { $("e-" + key).checked = onByDefault.includes(key) ? s[key] !== false : !!s[key]; });
  const next = detail.pages_in_folder + 1;
  $("e-next-number").textContent = `use ${next}, the number after the pages held`;
  $("e-next-number").onclick = () => { $("e-increment").value = next; };

  const runs = detail.runs.map((r) => `<tr><td>${esc(when(r.started))}</td><td class="num">${r.pages_saved ?? ""}</td>
    <td>${esc(r.stop_reason || "")}${r.exit_code ? " (exit " + r.exit_code + ")" : ""}</td>
    <td>${r.last_page_number ?? ""}</td><td>${link(r.last_url)}</td></tr>`).join("");
  const edits = detail.edits.map((e) => `<div class="history-item line">${esc(when(e.at))}: ${esc(Object.entries(e.changed)
    .map(([key, pair]) => `${key} ${JSON.stringify(pair[0])} → ${JSON.stringify(pair[1])}`).join(", "))}</div>`).join("");
  $("edit-runs").innerHTML = (runs ? `<div class="table-wrap" style="max-height:none"><table class="runs"><thead><tr><th>Started</th>
    <th>Saved</th><th>Ended</th><th>At #</th><th>Last page</th></tr></thead><tbody>${runs}</tbody></table></div>` : "") +
    (edits ? `<div class="muted" style="margin-top:10px">Edits</div>${edits}` : "");
  $("edit-runs-box").hidden = !runs && !edits;

  const busy = detail.running;
  ["edit-save", "edit-save-update"].forEach((id) => { $(id).disabled = busy; });
  if (busy) { msg.className = "msg bad"; msg.textContent = "Being scraped right now; stop it or wait to edit."; }
  $("editor").showModal();
}

async function saveEditor(updateAfter) {
  const msg = $("edit-msg");
  msg.className = "msg"; msg.textContent = "Saving…";
  const settings = {
    url: $("e-url").value, increment: $("e-increment").value, cbz_path: $("e-cbz_path").value,
    waittime: $("e-waittime").value, chapters_url: $("e-chapters").value, chapters_every: $("e-every").value,
  };
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
    msg.className = "msg good";
    msg.textContent = (result.from === "addresses" ? "Queued, reading the comic's own addresses. "
      : result.from === "every" ? `Queued, cutting it every ${$("e-every").value.trim()} pages. ` : "Queued. ")
      + (result.numbers_first ? "Where every file carries its page number it is cut from those; otherwise it walks the comic first. Watch it under Running now."
        : result.carrying_on ? "The record of which page is which stops short of the newest page, so the walk carries on from where it stopped; watch it under Running now."
        : result.walking ? "It walks the comic first, which takes a few minutes; watch it under Running now."
        : "Watch it under Running now.");
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
$("edit-save").addEventListener("click", () => saveEditor(false));
$("edit-save-update").addEventListener("click", () => saveEditor(true));
$("edit-cancel").addEventListener("click", () => $("editor").close());
