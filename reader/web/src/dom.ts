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

// the class that lays a cover in its card as it was said to fit; nothing for filling it, the way it always was
export function fitClass(fit: string | null | undefined): string {
  return fit === "width" ? "fit-width" : fit === "height" ? "fit-height" : "";
}

// what a refusal says, out of the server's answer: its detail where it gave one
export function refusal(error: unknown): string {
  const text = String(error instanceof Error ? error.message : error);
  const body = text.replace(/^\d+\s+/, "");
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  } catch { /* not json: said as it came */ }
  return text;
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
