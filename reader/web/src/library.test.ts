import { describe, expect, it } from "vitest";
import { browseHash } from "./library";

// main.ts reads back everything after the kind as one piece and decodes it whole
const readBack = (hash: string) => decodeURIComponent(hash.replace(/^#\/browse\/\w+\/?/, ""));

describe("addresses", () => {
  it("writes a folder's path with real slashes", () => {
    expect(browseHash("folder", "CBZs/SomeAuthor/TheirComic")).toBe("#/browse/folder/CBZs/SomeAuthor/TheirComic");
    expect(browseHash("folder")).toBe("#/browse/folder");
  });

  it("still encodes what a name holds, and reads back what it was given", () => {
    for (const path of ["CBZs/My Comic #1", "Uncompressed/50% & more", "A/B?c"]) {
      expect(readBack(browseHash("folder", path))).toBe(path);
    }
  });

  it("reads back a series named with a slash in it, and an address saved when slashes were %2F", () => {
    expect(readBack(browseHash("series", "Either/Or"))).toBe("Either/Or");
    expect(readBack("#/browse/folder/CBZs%2FMyComic")).toBe("CBZs/MyComic");
  });
});
