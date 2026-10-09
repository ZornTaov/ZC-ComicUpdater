export function el(tag: string, className = ""): HTMLElement {
  const made = document.createElement(tag);
  if (className) made.className = className;
  return made;
}

// text from the library - a comic's title, a chapter's label - is the site's, and goes in as text
export function esc(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
