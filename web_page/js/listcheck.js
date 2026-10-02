//reading a chapter list before committing to it

//which comic it was opened for, if any. opened from Add comics it belongs to no comic, and must not
//quietly borrow whichever one the editor looked at last
let listFor = null;
function openListCheck(url, like, name) {
  listFor = name || null;
  $("lc-url").value = url || "";
  $("lc-like").value = like || "";
  $("lc-result").textContent = "";
  $("lc-msg").className = "msg"; $("lc-msg").textContent = "";
  $("listcheck").showModal();
  $("lc-url").focus();
}
$("open-listcheck").addEventListener("click", () => openListCheck("", "", null));
$("edit-checklist").addEventListener("click", () =>
  openListCheck($("e-chapters").value.trim(), editing.first_page_url || editing.settings.url, editing.name));
$("lc-close").addEventListener("click", () => $("listcheck").close());
$("lc-go").addEventListener("click", async () => {
  const msg = $("lc-msg"), url = $("lc-url").value.trim();
  if (!/^https?:\/\/\S+$/.test(url)) {
    msg.className = "msg bad"; msg.textContent = "Give the full address of the chapter list page.";
    return;
  }
  msg.className = "msg";
  msg.textContent = $("lc-browser").checked ? "Loading it in the browser…" : "Reading it…";
  $("lc-result").textContent = "";
  try {
    const result = await post("/api/trylist", { url: url, like: $("lc-like").value.trim(),
                                                name: listFor, browser: $("lc-browser").checked });
    $("lc-result").innerHTML = `<pre>${esc(result.output || "(it said nothing)")}</pre>`;
    msg.className = "msg good";
    msg.textContent = `Read in ${result.seconds}s. Nothing was saved.`;
  } catch (error) {
    msg.className = "msg bad";
    msg.textContent = error.message;
  }
});
