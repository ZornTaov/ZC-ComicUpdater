//Upload a comic: a .zip or .cbz sent whole, with its progress shown, then put in the library from a card -
//as it came when it was adopted before, or adopted from the card's form when it was not

let upPending = [];
let upRequest = null;

async function loadUploads() {
  try {
    const response = await fetch(api("/api/uploads"));
    upPending = (await response.json()).uploads || [];
  } catch (error) {
    upPending = [];
  }
  renderUploads();
}

function upSize(bytes) {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

function upCard(up) {
  const s = up.settings;
  const numbered = up.numbering !== "unnumbered";
  const what = `${up.pages} page${up.pages === 1 ? "" : "s"}, ${esc(up.numbering)}` +
    (up.last_number !== null && up.last_number !== undefined ? ` up to ${esc(up.last_number)}` : "");
  const leftOut = up.left_out ? `<div class="note">${up.left_out} other file${up.left_out === 1 ? " is" : "s are"}
    left out, being neither a page nor its settings: ${esc(up.left_out_sample.join(", "))}${up.left_out > 5 ? ", …" : ""}</div>` : "";
  const kept = s ? `<div class="field"><label>Its settings</label><div>
      ${s.ended ? "ended" : `carries on from ${link(s.url)} at page ${esc(s.increment)}`}${s.prefix ? ", numbering pages" : ""}${s.every ? `, in parts of ${esc(s.every)} pages` : ""}
      ${s.index_cache ? `<div class="note">Its record of which page is which (${esc(s.index_cache)}) does not come with an
        upload: put it in the config folder's index folder by hand, or the comic will be walked when its chapters are next worked out.</div>` : ""}
    </div></div>` : `
    <div class="field"><label>Last page you have</label>
      <input type="text" data-f="last_url" spellcheck="false" placeholder="https://example.com/comic/page-you-have">
      <div class="note">The next update saves it again and carries on. Or give the first page you do not have instead:</div></div>
    <div class="field"><label>First you don't</label>
      <input type="text" data-f="next_url" spellcheck="false" placeholder="https://example.com/comic/next-page"></div>
    <div class="field"><label>Options</label><div class="row">
      <label class="check"><input type="checkbox" data-f="ended"> ended, nothing more to fetch</label>
      <label class="check"><input type="checkbox" data-f="prefix" ${numbered ? "checked" : ""}> number new pages</label>
      <label class="check">from <input type="number" data-f="increment" min="0" style="width:90px"
        value="${up.last_number ?? ""}" placeholder="${up.pages}"></label>
      <label class="check">cut every <input type="number" data-f="every" min="1" style="width:80px" placeholder="off"> pages</label>
    </div></div>`;
  const shape = up.kind === "cbz" ? `
    <div class="field"><label>Keep it as</label><div class="row">
      <label class="check"><input type="radio" name="as-${esc(up.id)}" value="pages" data-f="as" checked> loose pages, to carry on scraping</label>
      <label class="check"><input type="radio" name="as-${esc(up.id)}" value="archive" data-f="as"> this archive, as it is</label>
    </div></div>` : "";
  return `<div class="check-box" data-up="${esc(up.id)}" style="margin-top:10px">
    <div><b>${esc(up.file)}</b> <span class="muted">· ${what} · ${upSize(up.bytes)} · ${up.adopted ? "adopted before" : "not adopted yet"}</span></div>
    ${leftOut}
    <div class="field" style="margin-top:8px"><label>Folder</label>
      <input type="text" data-f="folder" spellcheck="false" value="${esc(up.suggested)}" placeholder="MyComic"></div>
    ${shape}
    <div class="field"><label>Archive</label>
      <input type="text" data-f="cbz" spellcheck="false" placeholder="${esc(defaultCbz(up.suggested) || "MyComic/MyComic.cbz")}"></div>
    ${kept}
    <div class="field" data-replace hidden><label>Already there</label>
      <label class="check"><input type="checkbox" data-f="replace"> replace it, keeping the old one in .replaced</label></div>
    <div class="row">
      <button type="button" class="primary" data-up-place>Put it in the library</button>
      <button type="button" data-up-discard>Discard</button>
    </div>
    <div class="msg" data-up-msg></div>
  </div>`;
}

function renderUploads() {
  $("up-pending").innerHTML = upPending.map(upCard).join("");
}

function upValues(card) {
  const values = { id: card.dataset.up };
  card.querySelectorAll("[data-f]").forEach((input) => {
    const key = input.dataset.f;
    if (input.type === "radio") { if (input.checked) values[key] = input.value; }
    else if (input.type === "checkbox") values[key] = input.checked;
    else values[key] = input.value.trim();
  });
  return values;
}

$("up-send").addEventListener("click", () => {
  const file = $("up-file").files[0];
  const msg = $("up-msg");
  msg.className = "msg";
  msg.textContent = "";
  if (!file) { msg.className = "msg bad"; msg.textContent = "Choose a .zip or .cbz first."; return; }
  //sent as the body itself rather than a form, so the server can write it to disk as it arrives; the type
  //is one a page on another site could not send without asking first
  const request = new XMLHttpRequest();
  upRequest = request;
  request.open("POST", api("/api/upload"));
  request.setRequestHeader("Content-Type", "application/zip");
  request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  const started = Date.now();
  $("up-progress-row").hidden = false;
  $("up-send").disabled = true;
  request.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    $("up-progress").value = event.loaded / event.total;
    const rate = event.loaded / Math.max(1, (Date.now() - started) / 1000);
    $("up-progress-text").textContent = `${upSize(event.loaded)} of ${upSize(event.total)}` +
      (event.loaded < event.total ? ` · ${clock((event.total - event.loaded) / Math.max(rate, 1))} left` : " · looking inside");
  };
  const finish = (text, good) => {
    upRequest = null;
    $("up-progress-row").hidden = true;
    $("up-send").disabled = false;
    msg.className = good ? "msg good" : "msg bad";
    msg.textContent = text;
  };
  request.onload = () => {
    let data = {};
    try { data = JSON.parse(request.responseText); } catch (error) {}
    if (request.status !== 200) { finish(data.error || request.statusText, false); return; }
    $("up-file").value = "";
    finish(`Received ${data.file}. Say where it goes below.`, true);
    loadUploads();
  };
  request.onerror = () => finish("The upload stopped: the connection went.", false);
  request.onabort = () => finish("Upload cancelled; nothing was kept.", false);
  request.send(file);
});

$("up-cancel").addEventListener("click", () => { if (upRequest) upRequest.abort(); });

$("up-pending").addEventListener("input", (event) => {
  //the archive's default follows the folder, as it does in Add comics
  if (event.target.dataset.f !== "folder") return;
  const card = event.target.closest("[data-up]");
  card.querySelector('[data-f="cbz"]').placeholder = defaultCbz(event.target.value) || "MyComic/MyComic.cbz";
});

$("up-pending").addEventListener("click", async (event) => {
  const card = event.target.closest("[data-up]");
  if (!card) return;
  const msg = card.querySelector("[data-up-msg]");
  if (event.target.matches("[data-up-discard]")) {
    try {
      await post("/api/upload/discard", { id: card.dataset.up });
      loadUploads();
    } catch (error) { msg.className = "msg bad"; msg.textContent = error.message; }
    return;
  }
  if (!event.target.matches("[data-up-place]")) return;
  msg.className = "msg";
  msg.textContent = "";
  const response = await fetch(api("/api/upload/place"), { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(upValues(card)) });
  const data = await response.json().catch(() => ({}));
  if (response.status === 409) {
    //something is already there: offer to replace it, which is never done unasked
    card.querySelector("[data-replace]").hidden = false;
    msg.className = "msg bad";
    msg.textContent = data.error;
    return;
  }
  if (!response.ok) { msg.className = "msg bad"; msg.textContent = data.error || response.statusText; return; }
  $("up-msg").className = "msg good";
  $("up-msg").textContent = `Queued: ${data.label}. Recent says how it went.`;
  upPending = upPending.filter((up) => up.id !== card.dataset.up);
  renderUploads();
});
