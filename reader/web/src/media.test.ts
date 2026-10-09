import { describe, expect, it } from "vitest";
import { youtubeEmbed } from "./media";

describe("youtube", () => {
  it("embeds a video however the note links it", () => {
    const id = "xJytGuN4mDg";
    for (const address of [
      `https://www.youtube.com/embed/${id}?feature=oembed`,
      `https://www.youtube.com/watch?v=${id}`,
      `https://youtube.com/watch?feature=share&v=${id}&t=10`,
      `https://youtu.be/${id}`,
      `https://www.youtube.com/shorts/${id}`,
    ]) {
      expect(youtubeEmbed(address)).toBe(`https://www.youtube-nocookie.com/embed/${id}`);
    }
  });

  it("leaves any other link alone", () => {
    expect(youtubeEmbed("https://example.com/watch?v=xJytGuN4mDg")).toBeNull();
    expect(youtubeEmbed("https://www.youtube.com/channel/somebody")).toBeNull();
  });
});
