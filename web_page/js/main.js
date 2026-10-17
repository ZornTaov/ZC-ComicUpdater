//every file is loaded by now, so the page can draw itself and start polling

//every dialog closes from the × in its head, Escape, or a click beside it
document.querySelectorAll("dialog").forEach(closeOnBackdrop);
renderAddRows();
loadPlugins();
loadUploads();
loadConfig(false);
loadComics();
poll();
