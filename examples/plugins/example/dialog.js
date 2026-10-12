//the example plugin's own form on the updater's web page, in place of the one built from plugin.json's
//fields. a plugin needs this only when that one will not do - to explain its settings, or to lay them out
//its own way. it is loaded when the plugin is first chosen, and puts itself in pluginForms under the
//plugin's folder name, giving:
//  render(container, values, fields) - fill container with inputs showing values. fields is plugin.json's
//                                      fields, less any the page asks for itself (the address, on Add)
//  read(container)                   - the settings as typed, by key; the updater checks them
//esc() is the page's own, for putting text into html.
pluginForms["example"] = {
  render(container, values, fields) {
    const has = (key) => fields.some((field) => field.key === key);
    container.innerHTML = `
      <div class="muted" data-example-form style="flex-basis:100%">A made-up series, drawn rather than fetched:
        say how long it is, and each run takes in what it has not got yet.</div>
      ${has("url") ? `<label class="check">Series <input type="text" data-key="url" spellcheck="false"
        value="${esc(values.url || "")}" placeholder="https://example.com/comics/MyComic"></label>` : ""}
      <label class="check">Chapters <input type="number" min="0" data-key="chapters"
        value="${esc(values.chapters ?? 3)}"></label>
      <label class="check">of <input type="number" min="1" data-key="pages"
        value="${esc(values.pages ?? 2)}"> pages each</label>`;
  },
  read(container) {
    const values = {};
    container.querySelectorAll("[data-key]").forEach((input) => { values[input.dataset.key] = input.value; });
    return values;
  },
};
