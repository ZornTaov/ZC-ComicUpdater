//the Plugins dialog: the plugins there are, each updated from its repository or removed, and a new one
//installed from its git address. each is a job in the queue, whose git and pip output goes to the log; the
//list is read again when a job finishes, which running.js sees. a plugin with settings of its own - its
//plugin.json's "setup", the same for every comic of it - has them edited here too, saved at once

//the plugins whose settings are open, kept open when the list is drawn again
const setupOpen = new Set();

//one input a setting. a secret is masked until Show is pressed: whoever can reach this page may see it,
//but it need not be on the screen for anyone looking over a shoulder
function setupField(plugin, field) {
  const id = `pl-set-${plugin.name}-${field.key}`.replace(/[^A-Za-z0-9_-]/g, "_");
  const key = esc(field.key), value = field.value ?? "";
  const note = [field.help ? esc(field.help) : "", `Handed to its program as ${esc(field.env)}.`].filter(Boolean).join(" ");
  let input;
  if (field.type === "flag") {
    input = `<label class="check"><input type="checkbox" id="${id}" data-plugin-field="${key}" ${value ? "checked" : ""}> on</label>`;
  } else if (field.type === "secret") {
    input = `<span class="secret-in"><input type="password" id="${id}" data-plugin-field="${key}" spellcheck="false"
        autocomplete="off" value="${esc(value)}"><button type="button" class="small" data-show-secret="${id}">Show</button></span>`;
  } else {
    const kind = field.type === "count" ? 'type="number" min="0"' : 'type="text" spellcheck="false"';
    input = `<input ${kind} id="${id}" data-plugin-field="${key}" value="${esc(value)}"
      placeholder="${esc(field.placeholder || (field.type === "url" ? "https://example.com/..." : ""))}">`;
  }
  return `<div class="field"><label for="${id}">${esc(field.label || field.key)}</label>${input}
    <div class="note">${note}</div></div>`;
}

function setupForm(plugin) {
  return plugin.setup.map((field) => setupField(plugin, field)).join("") +
    `<div class="setup-foot"><button type="button" class="small primary" data-plugin-setup-save="${esc(plugin.name)}">Save settings</button></div>`;
}

async function saveSetup(name) {
  const plugin = pluginNamed(name), form = document.querySelector(`[data-setup-for="${CSS.escape(name)}"]`);
  if (!plugin || !form) return;
  const msg = $("pl-msg");
  try {
    const result = await post("/api/plugins/setup", { name, values: readFields(form) });
    plugin.setup = result.setup;
    form.innerHTML = setupForm(plugin);
    msg.className = "msg good";
    msg.textContent = `${plugin.title}'s settings are saved; its next run uses them.`;
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
}

function pluginRow(plugin) {
  const facts = [plugin.version != null ? `version ${esc(plugin.version)}` : "",
    plugin.repository ? "from its repository" : "put in by hand",
    plugin.env === "ready" ? "packages installed" : plugin.env === "to build" ? "packages installed by its next run" : ""]
    .filter(Boolean).join(" · ");
  const missing = plugin.missing && plugin.missing.length
    ? `<div class="bad">Needs ${esc(plugin.missing.join(", "))}, which this image does not have.</div>` : "";
  const may = pluginSetup.may_install;
  const hasSetup = plugin.setup && plugin.setup.length, open = hasSetup && setupOpen.has(plugin.name);
  return `<div class="plugin-row">
    <div class="grow"><b>${esc(plugin.title)}</b> <span class="muted">${esc(plugin.name)}</span>
      <div class="muted">${facts}</div>
      ${plugin.about ? `<div>${esc(plugin.about)}</div>` : ""}${missing}
      ${hasSetup ? `<div class="plugin-setup" data-setup-for="${esc(plugin.name)}" ${open ? "" : "hidden"}>${open ? setupForm(plugin) : ""}</div>` : ""}</div>
    <span>${hasSetup ? `<button type="button" class="small" data-plugin-settings="${esc(plugin.name)}">Settings</button>` : ""}
      ${plugin.repository ? `<button type="button" class="small" data-plugin-update="${esc(plugin.name)}"
        ${may ? "" : "disabled"}>Update</button>` : ""}
      <button type="button" class="small danger" data-plugin-remove="${esc(plugin.name)}"
        ${may ? "" : "disabled"}>Remove</button></span>
  </div>`;
}

function drawPluginsDialog() {
  $("pl-folder").textContent = pluginSetup.folder || "";
  const problems = (pluginSetup.problems || []).map((problem) =>
    `<div class="plugin-row bad">Cannot be used: ${esc(problem)}</div>`).join("");
  //an open settings form is carried over as it is, not drawn afresh: the list is read again as the dialog
  //opens and whenever a job finishes, and either landing while one was open threw away what was typed in it.
  //only while the plugin still asks for the same settings - one updated to ask for others is drawn anew
  const kept = new Map([...$("pl-list").querySelectorAll("[data-setup-for]:not([hidden])")]
    .map((form) => [form.dataset.setupFor, form]));
  $("pl-list").innerHTML = (pluginList.length || problems)
    ? pluginList.map(pluginRow).join("") + problems
    : `<div class="empty">No plugins yet.</div>`;
  kept.forEach((form, name) => {
    const fresh = $("pl-list").querySelector(`[data-setup-for="${CSS.escape(name)}"]`), plugin = pluginNamed(name);
    const asked = plugin && (plugin.setup || []).map((field) => field.key).join("\n");
    const has = [...form.querySelectorAll("[data-plugin-field]")].map((input) => input.dataset.pluginField).join("\n");
    if (fresh && asked === has) fresh.replaceWith(form);
  });
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
  const settings = event.target.dataset.pluginSettings, save = event.target.dataset.pluginSetupSave;
  const show = event.target.dataset.showSecret;
  if (settings) {
    const form = document.querySelector(`[data-setup-for="${CSS.escape(settings)}"]`);
    const opening = form.hidden;
    if (opening) { setupOpen.add(settings); form.innerHTML = setupForm(pluginNamed(settings)); }
    else setupOpen.delete(settings);
    form.hidden = !opening;
  }
  if (save) saveSetup(save);
  if (show) {
    const input = $(show), hidden = input.type === "password";
    input.type = hidden ? "text" : "password";
    event.target.textContent = hidden ? "Hide" : "Show";
  }
  const update = event.target.dataset.pluginUpdate, remove = event.target.dataset.pluginRemove;
  if (update) pluginJob("/api/plugins/update", { name: update }, "Queueing…");
  if (remove) {
    const btn = event.target;
    if (btn.dataset.pluginConfirm) {
      delete btn.dataset.pluginConfirm;
      btn.textContent = "Remove";
      btn.classList.remove("confirming");
      pluginJob("/api/plugins/remove", { name: remove }, "Queueing…");
    } else {
      btn.dataset.pluginConfirm = "1";
      btn.textContent = "Really Remove?";
      btn.classList.add("confirming");
      setTimeout(() => {
        if (btn.dataset.pluginConfirm) {
          delete btn.dataset.pluginConfirm;
          btn.textContent = "Remove";
          btn.classList.remove("confirming");
        }
      }, 5000);
    }
  }
});
