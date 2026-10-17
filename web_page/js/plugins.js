//scraper plugins: the list of them, and a plugin's settings as a form - one built from what its plugin.json
//says each setting is, or the one its own dialog.js draws. used by Add comics and by the editor.
//
//a plugin's dialog.js is loaded the first time it is needed, which is after main.js has run, and it says
//what it draws by putting itself in pluginForms as it loads - the one script that does anything as it
//loads besides main.js, and safe to, since everything it could use is loaded by then:
//
//  pluginForms["<plugin folder name>"] = {
//    render(container, values, fields) { ...fill container with inputs, showing values... },
//    read(container) { return { key: value, ... }; },
//  };

let pluginList = [];
//the rest of what the list said: what cannot be used, and whether plugins can be installed from here
let pluginSetup = {};
const pluginForms = {};
const pluginScripts = {};

//asked once as the page opens, and asked again until it is answered: a request that failed - the server
//busy, a restart under way - left the list empty, and the Scraper picker hidden, until the page was reloaded
async function loadPlugins(wait = 2000) {
  try {
    const response = await fetch(api("/api/plugins"));
    if (!response.ok) throw new Error(response.statusText);
    const found = await response.json();
    pluginList = found.plugins || [];
    pluginSetup = found;
    (found.problems || []).forEach((problem) => console.warn("plugin: " + problem));
    if ($("plugins").open) drawPluginsDialog();
  } catch (error) {
    console.warn("could not list the plugins, asking again: " + error.message);
    setTimeout(() => loadPlugins(Math.min(wait * 2, 30000)), wait);
  }
  showScrapers();
}

function pluginNamed(name) {
  return pluginList.find((plugin) => plugin.name === name) || null;
}

//one input a setting, by what plugin.json says it is: an address or text, a count, or a flag
function fieldsForm(fields, values) {
  return fields.map((field) => {
    const value = values[field.key] ?? field.default ?? "";
    const label = esc(field.label || field.key), key = esc(field.key), help = esc(field.help || "");
    if (field.type === "flag") {
      return `<label class="check" title="${help}"><input type="checkbox" data-plugin-field="${key}"
        ${value ? "checked" : ""}> ${label}</label>`;
    }
    const kind = field.type === "count" ? 'type="number" min="0"' : 'type="text" spellcheck="false"';
    return `<label class="check" title="${help}">${label} <input ${kind} data-plugin-field="${key}"
      value="${esc(value)}" placeholder="${esc(field.placeholder || (field.type === "url" ? "https://example.com/..." : ""))}"></label>`;
  }).join("");
}

function readFields(container) {
  const values = {};
  container.querySelectorAll("[data-plugin-field]").forEach((input) => {
    values[input.dataset.pluginField] = input.type === "checkbox" ? input.checked : input.value;
  });
  return values;
}

//a plugin's own dialog.js and dialog.css, fetched once however often its form is drawn
function pluginScript(plugin) {
  if (!plugin.dialog) return Promise.resolve();
  if (!pluginScripts[plugin.name]) {
    const base = api(`/plugins/${encodeURIComponent(plugin.name)}/`);
    //the stamp changes with the files, so an updated plugin's form is not one a cache along the way kept
    const stamp = plugin.stamp ? `?v=${plugin.stamp}` : "";
    if (plugin.style) {
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = base + "dialog.css" + stamp;
      document.head.appendChild(style);
    }
    pluginScripts[plugin.name] = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = base + "dialog.js" + stamp;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`${plugin.title}'s dialog.js could not be loaded`));
      document.head.appendChild(script);
    });
  }
  return pluginScripts[plugin.name];
}

//a plugin's settings drawn into a container: by its own dialog if it has one that loads, and otherwise
//from its fields, so a plugin whose dialog is broken can still be added and edited
async function drawPluginForm(container, plugin, values, leaveOut = []) {
  const fields = plugin.fields.filter((field) => !leaveOut.includes(field.key));
  container.dataset.plugin = plugin.name;
  let own = null;
  try {
    await pluginScript(plugin);
    own = pluginForms[plugin.name] || null;
  } catch (error) {
    console.warn(error.message);
  }
  //the form may have been put away, or another plugin chosen, while the script loaded
  if (container.dataset.plugin !== plugin.name) return;
  if (own) {
    container.innerHTML = "";
    own.render(container, values, fields);
  } else {
    container.innerHTML = fieldsForm(fields, values);
  }
}

function readPluginForm(container) {
  const own = pluginForms[container.dataset.plugin];
  return own ? own.read(container) : readFields(container);
}

function clearPluginForm(container) {
  delete container.dataset.plugin;
  container.innerHTML = "";
}

//a plugin comic's settings as its plugin's fields: its own, and the address every comic keeps
function pluginValues(settings) {
  const values = Object.assign({}, settings.plugin || {});
  if (settings.url) values.url = settings.url;
  return values;
}

//the Scraper picker on Add comics, shown only once there is a plugin to pick
function showScrapers() {
  const picker = $("add-scraper"), chosen = picker.value;
  picker.innerHTML = `<option value="">Built in</option>` + pluginList.map((plugin) =>
    `<option value="${esc(plugin.name)}">${esc(plugin.title)}</option>`).join("");
  picker.value = pluginNamed(chosen) ? chosen : "";
  //a row lays itself out as flex, which the hidden attribute does not overrule
  $("add-scraper-row").style.display = pluginList.length ? "" : "none";
  chooseScraper();
}
