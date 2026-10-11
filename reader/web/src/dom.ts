export function el(tag: string, className = ""): HTMLElement {
  const made = document.createElement(tag);
  if (className) made.className = className;
  return made;
}

// a picture chosen from the device, or null when the choosing is given up
export function pickPicture(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

// what a cover being set has to say: where on the shelf it went, or why it did not
export function coverMessage(set: { shelf?: string | null; note: string | null }): string {
  if (set.note) return `Cover set, ${set.note}`;
  return set.shelf ? `Cover set, and saved as ${set.shelf}` : "Cover set";
}

// text from the library - a comic's title, a chapter's label - is the site's, and goes in as text
export function esc(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
