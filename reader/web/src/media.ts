// a page that is not a picture, shown as what it is: a video plays where the page is, a note naming a
// YouTube video embeds it, and flash runs in Ruffle. anything else keeps the stand-in picture, with a button
// to open the link.
import type { StandIn } from "./api";

// the YouTube video an address names, in any of the shapes a site links one, as the address to embed it.
// youtube.com itself, not its no-cookie host: that one hides the viewer's own sign-in from the player on
// purpose, and YouTube now answers an anonymous embedded viewer with "sign in to confirm you're not a bot" -
// which signing in cannot satisfy, since the player still will not see it
export function youtubeEmbed(address: string): string | null {
  const found = address.match(/(?:youtube(?:-nocookie)?\.com\/(?:embed\/|shorts\/|v\/|watch\?(?:[^#]*&)?v=)|youtu\.be\/)([\w-]{11})/);
  return found ? `https://www.youtube.com/embed/${found[1]}` : null;
}

// Ruffle, the flash player written for browsers (MIT/Apache), served from beside the page so it works with
// no internet - copied there by copy-ruffle.mjs at build time - and fetched only the first time a flash page
// is opened, since it is several megabytes the rest of the page never needs
const RUFFLE = "/ruffle/ruffle.js";
let ruffle: Promise<RufflePlayerApi> | null = null;

interface RufflePlayerApi {
  newest(): { createPlayer(): HTMLElement & { load(options: object): Promise<void> } };
}

declare global {
  interface Window { RufflePlayer?: RufflePlayerApi & { config?: object } }
}

function loadRuffle(): Promise<RufflePlayerApi> {
  if (!ruffle) {
    ruffle = new Promise((resolve, reject) => {
      window.RufflePlayer = Object.assign(window.RufflePlayer ?? {}, {
        config: { publicPath: "/ruffle/", autoplay: "on", unmuteOverlay: "visible", letterbox: "on",
                  splashScreen: false, contextMenu: "rightClickOnly" } }) as never;
      const script = document.createElement("script");
      script.src = RUFFLE;
      script.onload = () => window.RufflePlayer?.newest ? resolve(window.RufflePlayer) : reject(new Error("no Ruffle"));
      script.onerror = () => { ruffle = null; reject(new Error("could not fetch Ruffle")); };
      document.head.append(script);
    });
  }
  return ruffle;
}

interface Shape {
  width: number;
  height: number;
}

export interface Embed {
  element: HTMLElement;
  // run once the element is on the page: Ruffle will not load into an element that is not
  start(): void;
}

const nothing = () => undefined;

// the element to show in the page's place, or null to keep the stand-in picture
export async function embedFor(found: StandIn): Promise<Embed | null> {
  if (found.kind === "video" && found.url) {
    const video = document.createElement("video");
    video.className = "embed embed-video";
    video.src = found.url;
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    return { element: video, start: nothing };
  }
  if (found.kind === "link" && found.address) {
    const embed = youtubeEmbed(found.address);
    if (!embed) return null;
    const frame = document.createElement("iframe");
    frame.className = "embed embed-wide";
    frame.src = embed;
    frame.title = found.title || "Video";
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    return { element: frame, start: nothing };
  }
  if (found.kind === "flash" && found.url) {
    try {
      const api = await loadRuffle();
      const holder = document.createElement("div");
      holder.className = "embed embed-flash";
      const player = api.newest().createPlayer();
      holder.append(player);
      // the box takes the movie's own shape once Ruffle has read it: a flash comic is often a wide strip,
      // which a screen-shaped box would bury in black
      player.addEventListener("loadedmetadata", () => {
        const handle = player as unknown as { ruffle?: () => { metadata?: Shape }; metadata?: Shape };
        const shape = handle.ruffle?.().metadata ?? handle.metadata;
        if (shape?.width && shape?.height) holder.style.setProperty("--aspect", String(shape.width / shape.height));
      });
      // a load that fails leaves Ruffle's own message in its place
      return { element: holder, start: () => { player.load({ url: found.url }).catch(() => undefined); } };
    } catch {
      return null;
    }
  }
  return null;
}
