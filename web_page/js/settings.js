//the Settings dialog, and the Add comics options the page starts with, which it supplies

let config = null;

function applyConfig(data) {
  config = data;
  const s = data.settings;
  $("cfg-path").textContent = data.path + (data.saved ? "" : " (not written yet)");
  ["pages_folder", "cbz_folder", "jobs", "timeout", "progress", "max_depth"].forEach((key) => {
    $("c-" + key).value = s[key] ?? "";
  });
  $("c-schedule").value = s.schedule || "";
  ["jobs", "timeout", "progress", "max_depth", "schedule"].forEach((key) => {
    const note = $("c-" + key + "-note");
    if (note) note.textContent = data.from_command_line.includes(key) ? "· set on the command line, which wins" : "";
  });
  Object.entries(s.add_defaults || {}).forEach(([key, value]) => {
    const box = $("c-add-" + key);
    if (box) box.checked = !!value;
  });
  $("add-roots").textContent = `${s.pages_folder}/ and ${s.cbz_folder}/`;
  ["prime", "prefix", "javascript", "cbz", "direction"].forEach((key) => {
    const from = s.add_defaults || {};
    const box = $(key);
    if (box) box.checked = !!from[key === "direction" ? "direction_check" : key];
  });
  if (s.add_defaults) {
    $("increment").value = s.add_defaults.increment ?? 1;
    $("waittime").value = s.add_defaults.waittime ?? 0;
  }
}

async function loadConfig(open) {
  try {
    applyConfig(await (await fetch(api("/api/config"))).json());
    if (open) {
      $("cfg-msg").className = "msg"; $("cfg-msg").textContent = "";
      $("config").showModal();
    }
  } catch (error) {
    if (open) alert("Could not read the settings: " + error.message);
  }
}

$("open-config").addEventListener("click", () => loadConfig(true));
$("cfg-cancel").addEventListener("click", () => $("config").close());
$("cfg-save").addEventListener("click", async () => {
  const msg = $("cfg-msg");
  msg.className = "msg"; msg.textContent = "Saving…";
  const settings = { schedule: $("c-schedule").value.trim(), add_defaults: {} };
  ["pages_folder", "cbz_folder", "jobs", "timeout", "progress", "max_depth"].forEach((key) => {
    settings[key] = $("c-" + key).value;
  });
  ["prime", "prefix", "javascript", "cbz", "direction_check"].forEach((key) => {
    settings.add_defaults[key] = $("c-add-" + key).checked;
  });
  settings.add_defaults.increment = Number($("increment").value) || 1;
  settings.add_defaults.waittime = Number($("waittime").value) || 0;
  try {
    const result = await post("/api/config", { settings });
    applyConfig({ ...config, settings: result.settings, saved: true, path: result.path });
    msg.className = "msg good";
    msg.textContent = "Saved. The next run uses these; a changed schedule waits for a restart.";
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
