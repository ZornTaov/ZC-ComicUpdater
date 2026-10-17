// the boxes of a ComicInfo editor, for one comic or a whole folder: the nine every comic is asked about, then
// any other tag of the schema it says or is given. which tags there are, what each is called, and which take
// a number or one of a list are the server's to say - the scraper's page is drawn from the same lists
import { esc } from "./dom";

// [name, label, long]: a name is the metadata's for the nine ("writer"), the schema's for the rest ("Publisher")
export type FormField = [key: string, label: string, long: boolean];

export interface InfoForm {
  fields: FormField[];
  extra: FormField[];
  numbers: string[];
  choices: Record<string, string[]>;
}

export type Said = Record<string, string>;

// what a box shows besides its value: greyed, what it means left empty, or that the comics differ
export interface Box {
  value: string;
  hint?: string;
  // a row that can be taken off the form - every tag beyond the nine
  removable?: boolean;
}

// the tags beyond the nine that are shown, in the schema's order: those said or worked out, and those added
export function shownExtras(form: InfoForm, ...said: Said[]): string[] {
  return form.extra.map(([key]) => key).filter((key) => said.some((each) => (each[key] ?? "") !== ""));
}

// what is left to add, in the schema's order
export function addable(form: InfoForm, shown: string[]): FormField[] {
  return form.extra.filter(([key]) => !shown.includes(key));
}

export function fieldOf(form: InfoForm, key: string): FormField {
  return form.fields.find(([each]) => each === key) ?? form.extra.find(([each]) => each === key) ?? [key, key, false];
}

export function boxHtml(form: InfoForm, [key, label, long]: FormField, box: Box): string {
  const value = esc(box.value);
  const hint = box.hint ? esc(box.hint) : "";
  const choices = form.choices[key];
  const remove = box.removable ? `<button type="button" class="field-remove" data-remove="${esc(key)}" title="Take ${esc(label)} off">×</button>` : "";
  let input: string;
  if (choices) {
    // the empty choice is what an empty box is: the hint, where there is one
    const options = [`<option value="">${hint ? `(${hint})` : "—"}</option>`]
      .concat(choices.map((choice) => `<option${choice === box.value ? " selected" : ""}>${esc(choice)}</option>`));
    input = `<select name="${esc(key)}">${options.join("")}</select>`;
  } else if (long) {
    input = `<textarea name="${esc(key)}" rows="6"${hint ? ` placeholder="${hint}"` : ""}>${value}</textarea>`;
  } else {
    input = `<input name="${esc(key)}" value="${value}"${hint ? ` placeholder="${hint}"` : ""}${
      form.numbers.includes(key) ? ' inputmode="numeric"' : ""}>`;
  }
  return `<label class="field${long ? " long" : ""}" data-field="${esc(key)}"><span>${esc(label)}${remove}</span>${input}</label>`;
}

// the picker that puts another tag on the form
export function adderHtml(form: InfoForm, shown: string[]): string {
  const left = addable(form, shown);
  if (!left.length) return "";
  return `<label class="field field-add"><span>Add a field</span><select data-add>
    <option value="">Choose a tag…</option>${left.map(([key, label]) => `<option value="${esc(key)}">${esc(label)}</option>`).join("")}
  </select></label>`;
}

// what a box says now, trimmed
export function valueOf(form: HTMLFormElement, key: string): string {
  const input = form.elements.namedItem(key) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
  return input ? input.value.trim() : "";
}
