//the element paths dialog: the two lists as they are being edited, and checking a page against them

//each list the dialog edits, in the order they are shown, by what it is called there
const pathLabels = { image: "Comic image", next: "Next page", first: "First page" };
const pathKinds = Object.keys(pathLabels);
let paths = { image: [], next: [], first: [] };
let checkJob = null;
//the last page checked, kept so the path list can say what each path actually found there. a path that
//catches the buttons alongside the pages is worth seeing while the list is being edited, not afterwards
let lastCheck = null;

function checkedPaths(kind) {
  const found = {};
  ((lastCheck && lastCheck[kind]) || []).forEach((h, at) => {
    found[h.xpath] = { first: at === 0, count: h.count || 1, pages: h.page_count || 0 };
  });
  return found;
}

function pathBadge(kind, hit) {
  //always a cell, even when empty, so every row keeps the same columns and nothing shifts about
  if (!hit) return `<span class="ep-hit"></span>`;
  //a count only tells you something when it is not one, and "pages" only differs from it when some of the
  //matches were not pages at all
  const what = hit.count > 1
    ? `${hit.count} images${hit.pages !== hit.count ? `, ${hit.pages} pages` : ""}`
    : "matched";
  const why = hit.count > 1
    ? `the last check found ${hit.count} images with this path, ${hit.pages} of them pages of the comic`
    : "this path matched the last page checked";
  return `<span class="ep-hit ${hit.first ? "on" : ""}" title="${esc(why)}">${hit.first ? "used · " : ""}${what}</span>`;
}

function renderPaths(fromCheck) {
  //moving a row rebuilds the lists, and a rebuilt list would otherwise jump back to the top
  const scrolled = {};
  $("ep-lists").querySelectorAll(".ep-list").forEach((list) => { scrolled[list.dataset.list] = list.scrollTop; });
  //worked out once for every list, since a row cannot declare anything of its own inside the markup below
  const hits = Object.fromEntries(pathKinds.map((kind) => [kind, checkedPaths(kind)]));
  $("ep-lists").innerHTML = pathKinds.map((kind) => `
    <div class="ep-head"><h4>${pathLabels[kind]} paths</h4>
      <span class="muted">${paths[kind].filter((p) => p.enabled).length} on, ${paths[kind].length} listed${
        lastCheck && lastCheck.url ? `, counts from the check of ${esc(lastCheck.url)}` : ""}</span>
      <button type="button" class="link" data-add="${kind}">add one</button></div>
    <div class="ep-list" data-list="${kind}">${paths[kind].map((p, at) => `
      <div class="ep ${p.enabled ? "" : "off"} ${hits[kind][p.xpath] ? (hits[kind][p.xpath].first ? "hit-used" : "hit-some") : ""}" draggable="true" data-kind="${kind}" data-at="${at}">
        <span class="grip" title="drag to move">⠿</span>
        <input type="checkbox" ${p.enabled ? "checked" : ""} data-kind="${kind}" data-at="${at}" data-field="enabled"
          title="${p.enabled ? "in use" : "turned off"}">
        <input type="text" value="${esc(p.xpath)}" data-kind="${kind}" data-at="${at}" data-field="xpath" spellcheck="false">
        <input type="text" class="note-in" value="${esc(p.note || "")}" placeholder="note, e.g. the comic"
          data-kind="${kind}" data-at="${at}" data-field="note">
        ${pathBadge(kind, hits[kind][p.xpath])}
        <span class="moves">
          <button type="button" data-move="up" data-kind="${kind}" data-at="${at}" ${at === 0 ? "disabled" : ""} title="earlier">↑</button>
          <button type="button" data-move="down" data-kind="${kind}" data-at="${at}" ${at === paths[kind].length - 1 ? "disabled" : ""} title="later">↓</button>
          ${p.shipped ? `<button type="button" disabled title="came with the script">✕</button>`
            : `<button type="button" data-drop-path="1" data-kind="${kind}" data-at="${at}" title="remove">✕</button>`}
        </span>
      </div>`).join("")}</div>`).join("");
  $("ep-lists").querySelectorAll(".ep-list").forEach((list) => {
    if (scrolled[list.dataset.list]) list.scrollTop = scrolled[list.dataset.list];
    //a check just came back: the path it used is what you came to look at, and it can be anywhere in a
    //list this long. only then, since otherwise this would fight with whatever you were scrolled to
    const used = fromCheck && list.querySelector(".ep.hit-used");
    if (used) list.scrollTop = Math.max(used.offsetTop - list.clientHeight / 2, 0);
  });
}

// dragging a row by its grip, within its own list
let dragging = null;
$("ep-lists").addEventListener("dragstart", (event) => {
  const row = event.target.closest(".ep");
  if (!row) return;
  dragging = { kind: row.dataset.kind, at: Number(row.dataset.at) };
  row.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", "row");
});
$("ep-lists").addEventListener("dragover", (event) => {
  const row = event.target.closest(".ep");
  if (!dragging || !row || row.dataset.kind !== dragging.kind) return;
  event.preventDefault();
  $("ep-lists").querySelectorAll(".ep.over").forEach((other) => other.classList.remove("over"));
  row.classList.add("over");
});
$("ep-lists").addEventListener("drop", (event) => {
  const row = event.target.closest(".ep");
  if (!dragging || !row || row.dataset.kind !== dragging.kind) return;
  event.preventDefault();
  const list = paths[dragging.kind];
  const [moved] = list.splice(dragging.at, 1);
  list.splice(Number(row.dataset.at), 0, moved);
  dragging = null;
  renderPaths();
});
$("ep-lists").addEventListener("dragend", () => {
  dragging = null;
  $("ep-lists").querySelectorAll(".dragging, .over").forEach((row) => row.classList.remove("dragging", "over"));
});

async function openElements() {
  $("ep-msg").className = "msg"; $("ep-msg").textContent = "";
  try {
    const data = await (await fetch(api("/api/elements"))).json();
    paths = Object.fromEntries(pathKinds.map((kind) => [kind, data[kind] || []]));
    $("ep-path").textContent = data.problem ? data.problem : data.path + (data.saved ? "" : " (not written yet)");
    renderPaths();
    $("elements").showModal();
  } catch (error) {
    alert("Could not read the element paths: " + error.message);
  }
}

$("ep-lists").addEventListener("input", (event) => {
  const { kind, at, field } = event.target.dataset;
  if (!field) return;
  paths[kind][at][field] = field === "enabled" ? event.target.checked : event.target.value;
  if (field === "enabled") renderPaths();
});
$("ep-lists").addEventListener("click", (event) => {
  const d = event.target.dataset;
  if (d.move) {
    const at = Number(d.at), to = d.move === "up" ? at - 1 : at + 1;
    const list = paths[d.kind];
    [list[at], list[to]] = [list[to], list[at]];
    renderPaths();
  } else if (d.dropPath) {
    paths[d.kind].splice(Number(d.at), 1);
    renderPaths();
  } else if (d.add) {
    paths[d.add].unshift({ xpath: "", note: "", enabled: true, shipped: false });
    renderPaths();
    $("ep-lists").querySelector(`[data-list="${d.add}"] input[type=text]`).focus();
  }
});
$("ep-save").addEventListener("click", async () => {
  const msg = $("ep-msg");
  msg.className = "msg"; msg.textContent = "Saving…";
  try {
    await post("/api/elements", paths);
    msg.className = "msg good";
    msg.textContent = "Saved. The next comic to run uses these.";
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
$("ep-cancel").addEventListener("click", () => $("elements").close());
$("open-elements").addEventListener("click", openElements);

function addPath(kind, xpath, note) {
  paths[kind].unshift({ xpath, note: note || "", enabled: true, shipped: false });
  renderPaths();
  $("ep-msg").className = "msg";
  $("ep-msg").textContent = `Added to the top of the ${pathLabels[kind].toLowerCase()} paths. Save to keep it.`;
}

function hit(kind, xpath, detail, first) {
  const already = paths[kind].some((p) => p.xpath === xpath);
  return `<div class="hit">${first ? `<span class="first">used</span>` : ""}<code>${esc(xpath)}</code>
    <span class="muted">${esc(detail || "")}</span>
    ${already ? "" : `<button type="button" class="link" data-add-path="${esc(xpath)}" data-add-kind="${kind}">add it</button>`}</div>`;
}


function fileName(src) {
  return String(src || "").split("?")[0].split("/").pop();
}

function pageNotes(found, top) {
  //what the check learned about the page itself, rather than which paths matched it. both of these turn a
  //path that looks right into a run that saves nothing, or a fraction of what it should, so they are said
  //here where the path is being chosen rather than left for the log of a run that has already gone wrong
  const notes = [];
  if ((top.count || 1) > 1) {
    const names = (top.pages || []).map(fileName);
    const left = (top.count || 0) - (top.page_count || 0);
    notes.push(`<div class="note"><b>Several pages on one address.</b> That path finds ${top.count} images
      here, ${top.page_count} of them pages${left > 0 ? `, and ${left} carrying no page number, so left
      out as buttons rather than pages` : ""}. A run saves each in turn, numbered on from the last:
      <code>${esc(names.slice(0, 8).join(", "))}</code>${names.length > 8 ? " …" : ""}</div>`);
  }
  if (found.needs_javascript) {
    notes.push(`<div class="note warn"><b>This comic needs javascript.</b> That image is not in the page the
      server sends, only in the one javascript builds. A check runs with javascript on and a scrape runs
      with it off, so the path above will match nothing and the run will say only that the path is not
      stored — until <b>javascript</b> is ticked in this comic's settings.</div>`);
  }
  return notes.join("");
}

function renderCheck(found, host) {
  if (!found) return;
  if (found.error) {
    $("check-result").innerHTML = `<div class="s-failed">${esc(found.error)}</div>`;
    return;
  }
  lastCheck = found;
  //the path list is behind this dialog and may already be on screen, so its counts are brought up to date
  //here rather than waiting for it to be reopened. an untouched list has nothing to redraw yet
  if (paths.image.length || paths.next.length) renderPaths(true);
  const parts = [`<div class="muted">${esc(found.title || "")}</div>`];
  pathKinds.forEach((kind) => {
    const label = pathLabels[kind];
    const hits = found[kind] || [];
    if (kind === "first" && !hits.length) {
      //only a walk of a comic whose start was never recorded needs one, and a comic's own first page often
      //has no link back to itself, so this is said quietly and offers nothing to add
      parts.push(`<div style="margin-top:8px"><b>${label}</b>: <span class="muted">nothing matched, so a walk
        from this page could not find its way back to page 1</span></div>`);
      return;
    }
    if (hits.length) {
      parts.push(`<div style="margin-top:8px"><b>${label}</b>: ${hits.length} match${hits.length === 1 ? "" : "es"}</div>` +
        hits.map((h, at) => hit(kind, h.xpath, h.src || (h.found && (h.found.href || h.found.title || h.found.class)) || "", at === 0)).join("") +
        (kind === "image" ? pageNotes(found, hits[0]) : ""));
    } else {
      const guesses = (found.suggestions || {})[kind] || [];
      parts.push(`<div style="margin-top:8px"><b>${label}</b>: <span class="s-failed">nothing matched</span>${guesses.length ? ", but this is on the page:" : ""}</div>` +
        guesses.filter((g) => g.suggested).map((g) => hit(kind, g.suggested,
          [g.tag, g.size, g.alt, g.href].filter(Boolean).join(" · "), false)).join(""));
    }
  });
  $("check-result").innerHTML = parts.join("");
  $("check-result").dataset.host = host || "";
}

$("check-go").addEventListener("click", async () => {
  const url = $("check-url").value.trim();
  $("check-result").innerHTML = `<span class="muted">Checking… a browser has to start, so give it a moment.</span>`;
  try {
    const result = await post("/api/check", { url });
    checkJob = { id: result.queued, host: (url.split("/")[2] || "") };
  } catch (error) {
    $("check-result").innerHTML = `<div class="s-failed">${esc(error.message)}</div>`;
  }
});
$("check-result").addEventListener("click", (event) => {
  const xpath = event.target.dataset.addPath;
  if (xpath) {
    addPath(event.target.dataset.addKind, xpath, $("check-result").dataset.host);
    event.target.replaceWith(document.createTextNode("added"));
  }
});
