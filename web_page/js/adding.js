//Add comics: one row a comic, typed or filled from a pasted list, sent with the options beneath them

let addRows = [{ folder: "", cbz: "", url: "", chapters: "" }];
//the plugin whose program the comics being added are to be scraped by, or null for the built-in scraper
let addPlugin = null;

//the picker changed, or the plugins were read: the options the chosen scraper has, and no others
function chooseScraper() {
  addPlugin = pluginNamed($("add-scraper").value);
  $("add-section").classList.toggle("with-plugin", !!addPlugin);
  const address = addPlugin && addPlugin.fields.find((field) => field.key === "url");
  $("add-head-url").textContent = !addPlugin ? "First page" : address ? (address.label || "Address") : "";
  $("add-head-chapters").textContent = addPlugin ? "" : "Chapter list";
  $("add-scraper-about").textContent = addPlugin ? (addPlugin.about || "") : "";
  if (addPlugin) drawPluginForm($("add-plugin"), addPlugin, {}, ["url"]);
  else clearPluginForm($("add-plugin"));
  renderAddRows();
}

function defaultCbz(folder) {
  folder = folder.trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  if (!folder) return "";
  const parts = folder.split("/");
  return parts.length === 1 ? `${folder}/${parts[0]}.cbz` : folder + ".cbz";
}

function renderAddRows() {
  const focus = document.activeElement;
  const where = focus && focus.dataset && focus.dataset.addField
    ? [focus.dataset.at, focus.dataset.addField, focus.selectionStart] : null;
  //a plugin's comics have their chapters from it, and some plugins are given no address at all: the box
  //keeps its place, so the rows are laid out the same whichever scraper is chosen
  const address = addPlugin ? addPlugin.fields.find((field) => field.key === "url") : true;
  const unusedUrl = address ? "" : "unused", unusedChapters = addPlugin ? "unused" : "";
  const urlHint = addPlugin ? (address && address.placeholder) || "https://example.com/comic"
    : "https://example.com/comic/first-page";
  $("add-rows").innerHTML = addRows.map((row, at) => `
    <div class="add-row">
      <input type="text" value="${esc(row.folder)}" data-at="${at}" data-add-field="folder" spellcheck="false"
        placeholder="MyComic">
      <input type="text" value="${esc(row.cbz)}" data-at="${at}" data-add-field="cbz" spellcheck="false"
        placeholder="${esc(defaultCbz(row.folder) || "MyComic/MyComic.cbz")}">
      <input type="text" value="${esc(row.url)}" data-at="${at}" data-add-field="url" spellcheck="false"
        class="${unusedUrl}" placeholder="${esc(urlHint)}">
      <input type="text" value="${esc(row.chapters || "")}" data-at="${at}" data-add-field="chapters" spellcheck="false"
        class="${unusedChapters}" placeholder="archive page, for chapters">
      <button type="button" class="small" data-drop-row="${at}" ${addRows.length === 1 ? "disabled" : ""} title="remove">✕</button>
    </div>`).join("");
  if (where) {
    const back = $("add-rows").querySelector(`[data-at="${where[0]}"][data-add-field="${where[1]}"]`);
    if (back) { back.focus(); try { back.setSelectionRange(where[2], where[2]); } catch (e) {} }
  }
}

// a pasted list fills in rows: one comic per line, its columns split by | or tab, or just spaces
function splitPaste(text) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#"))
    .map((line) => {
      let parts = line.includes("|") ? line.split("|") : line.includes("\t") ? line.split("\t") : line.split(/\s+/);
      parts = parts.map((part) => part.trim()).filter(Boolean);
      //two addresses on a line are the first page and then the chapter list; everything else is a folder
      const urls = parts.filter((part) => /^https?:\/\//.test(part));
      const rest = parts.filter((part) => !urls.includes(part));
      return { folder: rest[0] || "", cbz: rest[1] || "", url: urls[0] || "", chapters: urls[1] || "" };
    });
}

$("add-rows").addEventListener("input", (event) => {
  const { at, addField } = event.target.dataset;
  if (!addField) return;
  addRows[at][addField] = event.target.value;
  if (addField === "folder") renderAddRows();
});
$("add-rows").addEventListener("paste", (event) => {
  const text = (event.clipboardData || window.clipboardData).getData("text");
  if (!/[\r\n]/.test(text.trim())) return;
  event.preventDefault();
  const at = Number(event.target.dataset.at);
  const filled = splitPaste(text);
  addRows.splice(at, addRows[at].folder || addRows[at].url ? 0 : 1, ...filled);
  renderAddRows();
});
$("add-rows").addEventListener("click", (event) => {
  const at = event.target.dataset.dropRow;
  if (at === undefined) return;
  addRows.splice(Number(at), 1);
  if (!addRows.length) addRows = [{ folder: "", cbz: "", url: "" }];
  renderAddRows();
});
$("add-more").addEventListener("click", () => {
  addRows.push({ folder: "", cbz: "", url: "", chapters: "" });
  renderAddRows();
  const inputs = $("add-rows").querySelectorAll('[data-add-field="folder"]');
  inputs[inputs.length - 1].focus();
});

$("add-scraper").addEventListener("change", chooseScraper);

//what is sent for comics a plugin's program scrapes: the rows, but for a chapter list, and its settings
function pluginAdd() {
  return {
    scraper: addPlugin.name,
    rows: addRows.map((row) => ({ folder: row.folder, cbz: row.cbz, url: row.url })),
    plugin: readPluginForm($("add-plugin")),
    cbz: $("cbz").checked,
  };
}

$("add").addEventListener("click", async () => {
  const msg = $("add-msg");
  msg.className = "msg";
  msg.textContent = "";
  try {
    const result = addPlugin ? await post("/api/add", pluginAdd()) : await post("/api/add", {
      rows: addRows,
      prime: $("prime").checked,
      prefix: $("prefix").checked,
      increment: $("increment").value,
      javascript: $("javascript").checked,
      waittime: $("waittime").value,
      cbz: $("cbz").checked,
      direction_check: $("direction").checked,
      every: $("add-every").value.trim(),
    });
    msg.className = "msg good";
    msg.textContent = `Queued: ${result.label}`;
    addRows = [{ folder: "", cbz: "", url: "", chapters: "" }];
    $("add-every").value = "";
    renderAddRows();
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
