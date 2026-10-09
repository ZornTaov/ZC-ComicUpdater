// Ruffle - the flash player written for browsers - goes into the build beside the page, so a flash page
// plays with no internet: the loader, its core and its two WebAssembly builds (one for browsers with the
// newer extensions, one without), and its licences. the source maps stay behind; they are most of its size.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";

const from = join("node_modules", "@ruffle-rs", "ruffle");
const to = join("dist", "ruffle");
mkdirSync(to, { recursive: true });
const taken = readdirSync(from).filter((name) => !name.endsWith(".map") && /\.(js|wasm)$|^LICENSE/.test(name));
for (const name of taken) copyFileSync(join(from, name), join(to, name));
console.log(`ruffle: ${taken.length} files into ${to}`);
