//chapter boundaries: correcting where a chapter starts, and putting in a page the comic's own links skip

let bounds = { name: "", list: [], fixes: [], pages: [] };

function pageAt(n) {
  return bounds.pages.find((p) => p.n === Number(n));
}

//what a page is called in the picker: its number, then whatever of its title is its own
function pageSaid(page) {
  return page.short || page.title || page.url;
}

//a browser filters its list by the option's value, so the value has to hold both things you might
//type: the page number and the page's name. the number is read back off the front of it. a comic whose
//titles differ only by their number ("Page 1", "Page 2") has no name beyond it, and "9 · 9" says nothing
function pageValue(page) {
  const said = String(pageSaid(page)).trim();
  return said === String(page.n) ? said : `${page.n} · ${said}`.slice(0, 90);
}

//what to send for a typed box: a page number if it names one, otherwise whatever was typed, so an
//address still works for a comic nobody has walked
function pageFrom(typed) {
  const said = String(typed || "").trim();
  const found = said.match(/^(\d+)(?:\s|·|$)/);
  return found ? found[1] : said;
}

function drawPicker() {
  $("bd-pages").innerHTML = bounds.pages.map((p) =>
    `<option value="${esc(pageValue(p))}"></option>`).join("");
  const note = $("bd-picked");
  if (!bounds.pages.length) {
    note.textContent = bounds.walked === false
      ? "This comic has not been walked, so its pages cannot be offered here. Type a page number, or the address of a page. Work out chapters walks it."
      : "";
  } else {
    note.textContent = `Pick from this comic's ${bounds.pages.length} pages by number, or type an address.`;
  }
}

//the name last filled in from a page, so it can be replaced when another page is chosen but a name
//typed by hand is never overwritten
let filledIn = "";

//as a page is typed or picked, say which page that is, so a boundary is not set on faith
function sayPicked() {
  const page = pageAt(pageFrom($("bd-new-at").value));
  const label = $("bd-new-label");
  if (!page) { drawPicker(); return; }
  $("bd-picked").textContent = `page ${page.n}: ${pageSaid(page)} — ${page.url}`;
  if (page.short && (!label.value.trim() || label.value === filledIn)) {
    label.value = page.short;
    filledIn = page.short;
  }
}

function drawBounds() {
  const held = new Set(bounds.fixes.map((f) => f.url));
  //a chapter whose starting address was never recorded is still named by its page number
  $("bd-rows").innerHTML = bounds.list.map((c) => `<tr data-url="${esc(c.start_url || String(c.start_page))}">
      <td class="muted">${c.number}</td>
      <td><input type="text" value="${esc(c.label || "")}" data-bd="label" spellcheck="false" style="width:100%"></td>
      <td><input type="text" value="${esc(pageAt(c.start_page) ? pageValue(pageAt(c.start_page)) : String(c.start_page))}"
                 data-bd="at" list="bd-pages" style="width:100%"></td>
      <td class="muted">${c.pages}</td>
      <td class="muted" title="${esc(c.start_url || "")}">${esc(
        (pageAt(c.start_page) && pageSaid(pageAt(c.start_page))) || c.start_file || "?")}</td>
      <td>${c.by_hand || held.has(c.start_url) ? `<button type="button" data-bd-act="forget">undo</button>` : ""}
          <button type="button" data-bd-act="drop" title="no chapter starts here; its pages join the one before">not a chapter</button></td>
    </tr>`).join("") || `<tr><td colspan="6" class="muted">No chapters have been worked out for this comic yet.</td></tr>`;
  $("bd-fixes").textContent = bounds.fixes.length
    ? `${bounds.fixes.length} correction(s) by hand, kept when the chapters are worked out again.`
    : "Nothing has been corrected by hand.";
}

async function sendFix(body) {
  const msg = $("bd-msg");
  const keep = $("bd-wrap").scrollTop;
  msg.className = "msg";
  msg.textContent = bounds.packed ? "Working it out and writing the archives that changed…" : "Working it out…";
  try {
    const result = await post("/api/chapterfix", Object.assign({ name: bounds.name }, body));
    const response = await fetch(api(`/api/comic?name=${encodeURIComponent(bounds.name)}`));
    const detail = await response.json();
    if (!response.ok) throw new Error(detail.error || response.statusText);
    editing = detail;
    bounds.list = detail.chapters.list || [];
    bounds.fixes = detail.chapters.fixes || [];
    bounds.packed = !!detail.chapters.packed;
    drawBounds();
    $("bd-wrap").scrollTop = keep;
    msg.className = "msg good";
    const wrote = (result.output || "").match(/wrote .+\.cbz/g);
    msg.textContent = wrote ? `Saved, and ${wrote.length} archive(s) written again: ${
      wrote.map((one) => one.slice(6)).join(", ").slice(0, 120)}` : "Saved.";
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
}

$("edit-boundaries").addEventListener("click", async () => {
  bounds = { name: editing.name, list: editing.chapters.list || [], fixes: editing.chapters.fixes || [],
             packed: !!editing.chapters.packed, pages: [] };
  $("bd-who").textContent = `${editing.name} — ${bounds.list.length} chapter(s)`;
  $("bd-msg").className = "msg"; $("bd-msg").textContent = "";
  $("bd-new-at").value = ""; $("bd-new-label").value = ""; $("bd-picked").textContent = "";
  drawBounds();
  drawPicker();
  $("bounds").showModal();
  //the comic's own pages, so a boundary can be chosen rather than guessed at. fetched after the dialog
  //is up, since it is a help rather than a thing to wait for
  try {
    const held = await post("/api/pages", { name: bounds.name });
    bounds.pages = held.pages || [];
    bounds.walked = held.walked;
    drawPicker();
    drawBounds();
  } catch (error) {
    $("bd-picked").textContent = "Could not read this comic's pages: " + error.message;
  }
});
$("bd-new-at").addEventListener("input", sayPicked);
$("bd-rows").addEventListener("click", (event) => {
  const act = event.target.dataset.bdAct;
  if (!act) return;
  const row = event.target.closest("tr");
  if (act === "drop" && !confirm("Its pages join the chapter before it. Sure?")) return;
  sendFix({ at: row.dataset.url, [act]: true });
});
$("bd-rows").addEventListener("change", (event) => {
  const what = event.target.dataset.bd;
  if (!what) return;
  const row = event.target.closest("tr");
  const at = pageFrom(row.querySelector('[data-bd="at"]').value);
  const label = row.querySelector('[data-bd="label"]').value.trim();
  if (!label) { $("bd-msg").className = "msg bad"; $("bd-msg").textContent = "A chapter needs a name."; return; }
  //moving a boundary is the same correction as naming one: this chapter starts at that page
  sendFix({ at: what === "at" ? at : row.dataset.url, label: label });
});
$("bd-add").addEventListener("click", () => {
  const at = pageFrom($("bd-new-at").value), label = $("bd-new-label").value.trim();
  if (!at || !label) { $("bd-msg").className = "msg bad"; $("bd-msg").textContent = "Give a page and a name."; return; }
  $("bd-new-at").value = ""; $("bd-new-label").value = ""; $("bd-picked").textContent = "";
  filledIn = "";
  sendFix({ at: at, label: label });
});
$("bd-reset").addEventListener("click", () => {
  if (!bounds.fixes.length) return;
  if (confirm("Undo every correction made by hand? The boundaries come back only when the chapters are worked out again.")) sendFix({ clear: true });
});
$("bd-close").addEventListener("click", () => $("bounds").close());

//putting in a page the comic's own links skip past
async function insertPage(dryRun) {
  const msg = $("bd-msg"), url = $("bd-in-url").value.trim(), after = pageFrom($("bd-in-after").value);
  if (!/^https?:\/\/\S+$/.test(url) || !after) {
    msg.className = "msg bad";
    msg.textContent = "Give the page's full address, and the page it follows.";
    return;
  }
  msg.className = "msg";
  msg.textContent = dryRun ? "Reading that page…" : "Reading it, then moving the pages after it…";
  $("bd-in-said").textContent = "";
  try {
    const result = await post("/api/insert", { name: bounds.name, url: url, after: after, dry_run: dryRun });
    $("bd-in-said").innerHTML = `<pre>${esc(result.output || "")}</pre>`;
    msg.className = "msg good";
    msg.textContent = dryRun ? "Nothing was changed." : "Done.";
    if (!dryRun) {
      $("bd-in-url").value = ""; $("bd-in-after").value = "";
      const held = await post("/api/pages", { name: bounds.name });
      bounds.pages = held.pages || [];
      const detail = await (await fetch(api(`/api/comic?name=${encodeURIComponent(bounds.name)}`))).json();
      bounds.list = (detail.chapters || {}).list || [];
      bounds.fixes = (detail.chapters || {}).fixes || [];
      drawPicker();
      drawBounds();
      //folded away again: the chapter list above is what you came back to look at
      $("bd-insert-box").open = false;
    }
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
}
$("bd-in-try").addEventListener("click", () => insertPage(true));
$("bd-in-go").addEventListener("click", () => insertPage(false));
