import { describe, expect, it } from "vitest";
import { underwayText } from "./underway";

const now = { what: "MyComic", done: 12, total: 94, told: 12, at: "MyComic - c013 - Part 13.cbz", seconds: 67.4 };

describe("what the bar says of an edit being written", () => {
  it("says how far it has got, and for how long", () => {
    expect(underwayText(now)).toBe("Writing ComicInfo of MyComic: 12 of 94 archives, 1m 07s");
  });
  it("says it is still checking before it knows how many there are", () => {
    expect(underwayText({ ...now, done: 0, total: 0, at: null, seconds: 2.5 }))
      .toBe("Checking MyComic before writing its ComicInfo… 2s");
  });
  it("says one archive as one", () => {
    expect(underwayText({ ...now, done: 0, total: 1, seconds: 0.4 })).toBe("Writing ComicInfo of MyComic: 0 of 1 archive, 0s");
  });
});
