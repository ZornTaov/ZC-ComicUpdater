//the Plugins dialog: the plugins there are, each updated from its repository or removed, and a new one
//installed from its git address. each is a job in the queue, whose git and pip output goes to the log; the
//list is read again when a job finishes, which running.js sees

function pluginRow(plugin) {
  const facts = [plugin.version != null ? `version ${esc(plugin.version)}` : "",
    plugin.repository ? "from its repository" : "put in by hand",
    plugin.env === "ready" ? "packages installed" : plugin.env === "to build" ? "packages installed by its next run" : ""]
    .filter(Boolean).join(" · ");
  const missing = plugin.missing && plugin.missing.length
    ? `<div class="bad">Needs ${esc(plugin.missing.join(", "))}, which this image does not have.</div>` : "";
  const may = pluginSetup.may_install;
  return `<div class="plugin-row">
    <div class="grow"><b>${esc(plugin.title)}</b> <span class="muted">${esc(plugin.name)}</span>
      <div class="muted">${facts}</div>
      ${plugin.about ? `<div>${esc(plugin.about)}</div>` : ""}${missing}</div>
    <span>${plugin.repository ? `<button type="button" class="small" data-plugin-update="${esc(plugin.name)}"
        ${may ? "" : "disabled"}>Update</button>` : ""}
      <button type="button" class="small danger" data-plugin-remove="${esc(plugin.name)}"
        ${may ? "" : "disabled"}>Remove</button></span>
  </div>`;
}

function drawPluginsDialog() {
  $("pl-folder").textContent = pluginSetup.folder || "";
  const problems = (pluginSetup.problems || []).map((problem) =>
    `<div class="plugin-row bad">Cannot be used: ${esc(problem)}</div>`).join("");
  $("pl-list").innerHTML = (pluginList.length || problems)
    ? pluginList.map(pluginRow).join("") + problems
    : `<div class="empty">No plugins yet.</div>`;
  //why not, said where the install would be: no password and no opt-in, or an image without git
  const whyNot = !pluginSetup.may_install ? pluginSetup.why_not
    : pluginSetup.git === false ? "This image has no git, so plugins cannot be installed or updated from here. Pull a newer image, or put a plugin's folder in by hand." : "";
  $("pl-why-not").textContent = whyNot || "";
  $("pl-why-not").hidden = !whyNot;
  const canInstall = pluginSetup.may_install && pluginSetup.git !== false;
  ["pl-url", "pl-ref", "pl-install"].forEach((id) => { $(id).disabled = !canInstall; });
}

async function pluginJob(path, body, doing) {
  const msg = $("pl-msg");
  msg.className = "msg"; msg.textContent = doing;
  try {
    const result = await post(path, body);
    msg.className = "msg good";
    msg.textContent = `Queued: ${result.label}. Running now and the log follow it, and this list is read again once it is done.`;
    return true;
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
    return false;
  }
}

$("open-plugins").addEventListener("click", async () => {
  $("pl-msg").className = "msg"; $("pl-msg").textContent = "";
  drawPluginsDialog();
  $("plugins").showModal();
  await loadPlugins();
});
$("pl-close").addEventListener("click", () => $("plugins").close());
$("pl-install").addEventListener("click", async () => {
  const url = $("pl-url").value.trim();
  if (!url) {
    $("pl-msg").className = "msg bad"; $("pl-msg").textContent = "Give the plugin's git address.";
    return;
  }
  if (await pluginJob("/api/plugins/install", { url, ref: $("pl-ref").value.trim() }, "Queueing…")) {
    $("pl-url").value = ""; $("pl-ref").value = "";
  }
});
$("pl-list").addEventListener("click", (event) => {
  const update = event.target.dataset.pluginUpdate, remove = event.target.dataset.pluginRemove;
  if (update) pluginJob("/api/plugins/update", { name: update }, "Queueing…");
  if (remove && confirm(`Remove the plugin ${remove}, its program and its packages? A plugin a comic still uses is not removed.`)) {
    pluginJob("/api/plugins/remove", { name: remove }, "Queueing…");
  }
});
