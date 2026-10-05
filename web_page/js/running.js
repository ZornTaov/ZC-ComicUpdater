//Running now, the queue, Recent and the log, all drawn from the one /api/state the page polls every two
//seconds

let seq = 0, lastHistoryId = null, lastHistoryHtml = null;

function comicLine(c) {
  const numbers = c.state === "waiting" ? "" :
    `${c.gained ? "+" + c.gained + " · " : ""}${clock(c.elapsed)}`;
  return `<div class="comic">
    <span class="tag s-${c.state}">${c.state}</span>
    <span class="name">${esc(c.name)}</span>
    <span class="num">${esc(c.detail && c.state !== "ok" ? c.detail : numbers)}</span>
    ${c.last_line ? `<span class="said" title="${esc(c.last_line)}">${esc(c.last_line)}</span>` : ""}
  </div>${c.tail && c.tail.length ? `<div class="tail">${esc(c.tail.join("\n"))}</div>` : ""}`;
}

function historyItem(j) {
  //an event rather than a job - the updater restarting - has a time and nothing to count
  if (j.kind === "restart") return `<div class="history-item">
    <div class="muted">${esc(j.label)}</div><div class="line">${when(j.finished)}</div></div>`;
  const counts = j.counts || {};
  const parts = [];
  if (j.gained) parts.push(`+${j.gained} pages`);
  if (counts.failed) parts.push(`${counts.failed} failed`);
  if (counts.stopped) parts.push(`${counts.stopped} stopped`);
  if (j.error) parts.push(j.error);
  //a job that is not about scraping says what it did instead: an upload put in the library
  if (j.outcome) parts.push(j.outcome);
  const notable = (j.comics || []).length;
  //stopped to ask rather than walking on its own, so it says so, and the editor is where it is answered
  if (j.decide) parts.push("stopped to ask what to do");
  return `<div class="history-item">
    <div><span class="${counts.failed || j.error || j.decide ? "s-failed" : ""}">${esc(j.label)}</span></div>
    <div class="line">${when(j.finished)} · took ${clock(j.finished - j.started)}${parts.length ? " · " + esc(parts.join(", ")) : " · nothing new"}</div>
    ${j.decide ? `<div class="line">${esc(j.decide.why)} <button type="button" class="link" data-open="${esc(j.decide.comic)}">Open its editor</button></div>` : ""}
    ${notable ? `<details data-job="${esc(String(j.id))}"><summary>${notable} comic${notable === 1 ? "" : "s"}</summary>${j.comics.map(comicLine).join("")}</details>` : ""}
  </div>`;
}

function quiet(j) {
  //nothing worth a line of its own: no pages, nothing failed or stopped, nothing to answer or report
  const counts = j.counts || {};
  return !j.gained && !counts.failed && !counts.stopped && !j.error && !j.outcome && !j.decide &&
    !(j.comics || []).length;
}

function quietRuns(history) {
  //a week of Recent was mostly the updater restarting and the same page checked over and over while an
  //element path was worked out. quiet entries of one kind in a row are drawn as one, newest first; anything
  //that did something stays on its own, and a run of them is never merged across one that did
  const groups = [];
  for (const j of history) {
    const last = groups[groups.length - 1];
    if (last && quiet(j) && quiet(last[0]) && j.kind === last[0].kind) last.push(j);
    else groups.push([j]);
  }
  return groups;
}

function historyGroup(group) {
  const newest = group[0], oldest = group[group.length - 1];
  const same = group.every((j) => j.label === newest.label);
  const label = same ? newest.label : `${newest.label}, and ${group.length - 1} more like it`;
  const each = group.map((j) => `<div class="line">${when(j.finished)}${same ? "" : " · " + esc(j.label)}${
    j.kind === "restart" ? "" : ` · took ${clock(j.finished - j.started)}`}</div>`).join("");
  //named by its oldest entry, which stays the same as newer ones join the run, so an opened run stays open
  return `<div class="history-item">
    <div class="${newest.kind === "restart" ? "muted" : ""}">${esc(label)}</div>
    <div class="line">${group.length} times, ${when(oldest.finished)} to ${when(newest.finished)}${
      newest.kind === "restart" ? "" : " · nothing new"}</div>
    <details data-job="${esc("run-" + oldest.id)}"><summary>each one</summary>${each}</details>
  </div>`;
}

function renderState(state) {
  $("root").textContent = state.root;
  $("next").textContent = state.next_run ? `next scheduled update ${when(state.next_run)}` : "no schedule";
  const job = state.current;
  $("stop").hidden = !job;
  if (job) {
    const counts = job.counts || {};
    const total = (job.comics || []).length;
    const done = (counts.ok || 0) + (counts.failed || 0) + (counts.stopped || 0);
    $("stop").disabled = job.stopping;
    $("stop").textContent = job.stopping ? "Stopping…" : "Stop";
    $("current").innerHTML = `<div class="job-title">${esc(job.label)}</div>
      <div class="muted">${total ? `${done} of ${total} done` : job.doing ? "running" : "starting"} · ${clock(state.now - job.started)}${job.gained ? ` · +${job.gained} pages` : ""}
        ${total || !job.doing ? `· ${state.jobs_at_once} at a time` : ""}</div>
      <div class="bar"><div style="width:${total ? (100 * done / total) : 0}%"></div></div>
      ${job.doing ? `<div class="comic"><span class="said" style="grid-column: 1 / 4" title="${esc(job.doing)}">${esc(job.doing)}</span></div>` : ""}
      ${(job.comics || []).filter((c) => c.state !== "ok" || c.gained).slice(0, 60).map(comicLine).join("")}
      ${counts.ok ? `<div class="muted" style="padding-top:6px">${counts.ok - (job.comics || []).filter((c) => c.state === "ok" && c.gained).length} already up to date</div>` : ""}`;
  } else {
    $("current").innerHTML = `<div class="empty">Nothing running.</div>`;
  }
  $("queue").innerHTML = state.waiting.length ? `<div class="muted" style="margin-top:12px">Queued</div>` +
    state.waiting.map((j) => `<div class="queue-item"><span>${esc(j.label)}</span>
      <button class="small" data-drop="${j.id}">Remove</button></div>`).join("") : "";

  const historyHtml = state.history.length ? quietRuns(state.history).map((group) =>
    group.length > 1 ? historyGroup(group) : historyItem(group[0])).join("") :
    `<div class="empty">Nothing has run in the last week.</div>`;
  //written over on every poll, an opened run would close again two seconds later. it only changes when a
  //job finishes, and then the runs that were open stay open
  if (historyHtml !== lastHistoryHtml) {
    const opened = new Set([...$("history").querySelectorAll("details[open]")].map((d) => d.dataset.job));
    $("history").innerHTML = historyHtml;
    $("history").querySelectorAll("details[data-job]").forEach((d) => { d.open = opened.has(d.dataset.job); });
    lastHistoryHtml = historyHtml;
  }

  if (checkJob) {
    const done = state.history.find((j) => j.id === checkJob.id);
    if (done) {
      renderCheck(done.check, checkJob.host);
      checkJob = null;
    } else if (state.current && state.current.id === checkJob.id) {
      $("check-result").innerHTML = `<span class="muted">Checking ${esc($("check-url").value.trim())}…</span>`;
    }
  }

  if (chapterJob) {
    const done = state.history.find((j) => j.id === chapterJob.id);
    if (done) {
      if (editing && editing.name === chapterJob.name && $("editor").open && done.decide) {
        showDecision(done.decide);
        $("edit-msg").className = "msg bad";
        $("edit-msg").textContent = "It stopped to ask what to do; the choices are above.";
      }
      chapterJob = null;
    }
  }

  // the library changes when a job finishes, so re-read it then rather than on every poll
  const newest = state.history.length ? state.history[0].id : null;
  if (newest !== lastHistoryId) {
    if (lastHistoryId !== null) loadComics();
    lastHistoryId = newest;
  }

  if (state.log.length) {
    const box = $("log");
    const html = state.log.map((l) => {
      const cls = /ERROR|FAILED|WARNING/.test(l.text) ? "bad" : /\+\d+ page/.test(l.text) ? "good" : "";
      const t = new Date(l.at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      return `<div class="${cls}"><span class="t">${t}</span> ${esc(l.text)}</div>`;
    }).join("");
    box.insertAdjacentHTML("beforeend", html);
    while (box.childElementCount > 2000) box.firstElementChild.remove();
    if ($("follow").checked) box.scrollTop = box.scrollHeight;
  }
  seq = state.seq;
}

async function poll() {
  try {
    const response = await fetch(api(`/api/state?since=${seq}`));
    if (!response.ok) throw new Error(response.statusText);
    renderState(await response.json());
    $("conn").textContent = "";
  } catch (error) {
    $("conn").innerHTML = `<span class="s-failed">not connected (${esc(error.message)})</span>`;
  }
  setTimeout(poll, 2000);
}

$("queue").addEventListener("click", async (event) => {
  const id = event.target.dataset.drop;
  if (id) await post("/api/drop", { id: Number(id) }).catch((e) => alert(e.message));
});
$("history").addEventListener("click", (event) => {
  const name = event.target.dataset.open;
  if (name) openEditor(name);
});
$("stop").addEventListener("click", async () => {
  if (confirm("Stop the running job? Pages already saved are kept, and the comic resumes from there next time.")) {
    await post("/api/stop").catch((e) => alert(e.message));
  }
});
