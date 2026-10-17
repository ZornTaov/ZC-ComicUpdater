//a comic's ComicInfo, opened from its editor: what its archives say it is, kept in its metadata's info block
//and written into every archive it has. the boxes are the server's lists - the same the reader's info page
//draws from - so the two never offer different things

//what the server said of the comic open here, the tags beyond the nine on the form, and those taken off it
let comicInfo = null;
let ciShown = [];
let ciRemoved = new Set();
let ciValues = {};

function ciField(key) {
  const form = comicInfo.form;
  return form.fields.find((field) => field[0] === key) || form.extra.find((field) => field[0] === key) || [key, key, false];
}

function ciBox([key, label, long], removable) {
  const form = comicInfo.form, value = ciValues[key] ?? "", hint = comicInfo.worked[key] || "";
  const id = "ci-f-" + key;
  let input;
  if (form.choices[key]) {
    input = `<select id="${id}" name="${esc(key)}"><option value="">${hint ? `(${esc(hint)})` : "—"}</option>${
      form.choices[key].map((choice) => `<option${choice === value ? " selected" : ""}>${esc(choice)}</option>`).join("")}</select>`;
  } else if (long) {
    input = `<textarea id="${id}" name="${esc(key)}" rows="4" placeholder="${esc(hint)}">${esc(value)}</textarea>`;
  } else {
    input = `<input type="text" id="${id}" name="${esc(key)}" value="${esc(value)}" placeholder="${esc(hint)}"
      ${form.numbers.includes(key) ? 'inputmode="numeric"' : ""}>`;
  }
  const remove = removable ? `<button type="button" data-ci-remove="${esc(key)}" title="Take ${esc(label)} off">×</button>` : "";
  return `<div class="field"><label for="${id}">${esc(label)}</label><div class="ci-in">${input}${remove}</div></div>`;
}

//what is typed is read back before the boxes are drawn again, so adding a tag keeps it
function ciKeep() {
  comicInfo.form.fields.map((field) => field[0]).concat(ciShown).forEach((key) => {
    const input = $("ci-boxes").querySelector(`[name="${key}"]`);
    if (input) ciValues[key] = input.value.trim();
  });
}

function ciDraw() {
  const form = comicInfo.form;
  const left = form.extra.filter((field) => !ciShown.includes(field[0]));
  $("ci-boxes").innerHTML = form.fields.map((field) => ciBox(field, false)).join("")
    + ciShown.map((key) => ciBox(ciField(key), true)).join("")
    + (left.length ? `<div class="field"><label for="ci-add">Add a field</label><select id="ci-add">
        <option value="">Choose a tag…</option>${left.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}
      </select></div>` : "");
}

async function openComicInfo() {
  const msg = $("ci-msg");
  msg.className = "msg"; msg.textContent = "";
  try {
    const response = await fetch(api(`/api/comicinfo?name=${encodeURIComponent(editing.name)}`));
    comicInfo = await response.json();
    if (!response.ok) throw new Error(comicInfo.error || response.statusText);
  } catch (error) {
    $("edit-msg").className = "msg bad";
    $("edit-msg").textContent = "Could not read its ComicInfo: " + error.message;
    return;
  }
  ciValues = {};
  Object.entries(comicInfo.said).forEach(([key, value]) => { ciValues[key] = String(value); });
  //every tag beyond the nine it says, or that is worked out for it, in the schema's order
  ciShown = comicInfo.form.extra.map((field) => field[0]).filter((key) => ciValues[key] || comicInfo.worked[key]);
  ciRemoved = new Set();
  $("ci-who").textContent = comicInfo.name;
  $("ci-chapters").textContent = comicInfo.chapters
    ? `Kept as ${comicInfo.chapters} chapter archives: each says the comic's series and who made it, but its own title and its first page's address.`
    : "";
  $("ci-save").textContent = comicInfo.cbz ? "Save and write the archives" : "Save";
  const busy = editing.running || editing.moving;
  $("ci-save").disabled = !!busy;
  if (busy) {
    msg.className = "msg bad";
    msg.textContent = editing.moving ? "Waiting to be moved; reopen it once the move has finished."
      : "Being scraped right now; stop it or wait to edit.";
  }
  ciDraw();
  $("comicinfo").showModal();
}

$("edit-comicinfo").addEventListener("click", openComicInfo);
$("ci-boxes").addEventListener("change", (event) => {
  if (event.target.id !== "ci-add" || !event.target.value) return;
  const key = event.target.value, order = comicInfo.form.extra.map((field) => field[0]);
  ciKeep();
  ciShown.push(key);
  ciShown.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  ciRemoved.delete(key);
  ciDraw();
  $("ci-f-" + key)?.focus();
});
$("ci-boxes").addEventListener("click", (event) => {
  const key = event.target.dataset.ciRemove;
  if (!key) return;
  ciKeep();
  ciShown.splice(ciShown.indexOf(key), 1);
  delete ciValues[key];
  ciRemoved.add(key);
  ciDraw();
});
$("ci-save").addEventListener("click", async () => {
  const msg = $("ci-msg");
  ciKeep();
  const info = {};
  comicInfo.form.fields.forEach(([key]) => { if (ciValues[key]) info[key] = ciValues[key]; });
  //a tag beyond the nine is named either way, empty taking it out; one never on the form is left be
  ciShown.forEach((key) => { info[key] = ciValues[key] || ""; });
  ciRemoved.forEach((key) => { info[key] = ""; });
  msg.className = "msg"; msg.textContent = "Saving…";
  try {
    const result = await post("/api/comicinfo", { name: comicInfo.name, updated: comicInfo.updated, info });
    //the editor beneath holds the metadata's stamp too, and would be told it had changed under it
    comicInfo.updated = result.updated;
    if (editing && editing.name === comicInfo.name) editing.updated = result.updated;
    msg.className = "msg good";
    msg.textContent = (result.saved ? "Saved." : "Nothing changed.") + (result.queued
      ? " Writing it into the archives is queued; watch it under Running now."
      : comicInfo.cbz ? "" : " This comic keeps no archives; any it is given will say it.");
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
$("ci-close").addEventListener("click", () => $("comicinfo").close());
