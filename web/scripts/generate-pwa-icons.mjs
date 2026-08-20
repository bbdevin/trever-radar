/**
 * Rasterize web/public/icons/trever-radar-mark.svg → PWA / favicon PNGs.
 * Does not redraw the mark; only exports sizes + a padded maskable variant.
 *
 * Usage: node scripts/generate-pwa-icons.mjs  (cwd = web/)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Resvg } from "@resvg/resvg-js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const iconsDir = join(root, "public", "icons");
const srcPath = join(iconsDir, "trever-radar-mark.svg");
const src = readFileSync(srcPath, "utf8");

function png(svg, size) {
  const resvg = new Resvg(svg, {
    fitTo: { mode: "width", value: size },
    background: "rgba(13,13,13,255)",
  });
  return resvg.render().asPng();
}

function write(name, buf) {
  const out = join(iconsDir, name);
  writeFileSync(out, buf);
  console.log(`wrote ${name} (${buf.length} bytes)`);
}

/** Inner 70% so TR + radar stay inside the maskable safe zone (80% circle). */
function maskableSvg(original) {
  const inner = original
    .replace(/<\?xml[^>]*>/i, "")
    .replace(/<svg[^>]*>/i, "")
    .replace(/<\/svg>\s*$/i, "")
    .trim();
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <rect width="1024" height="1024" fill="#0D0D0D"/>
  <svg x="154" y="154" width="716" height="716" viewBox="0 0 1024 1024">${inner}</svg>
</svg>`;
}

const maskable = maskableSvg(src);
writeFileSync(join(iconsDir, "trever-radar-mark-maskable.svg"), maskable, "utf8");
console.log("wrote trever-radar-mark-maskable.svg");

write("favicon-16.png", png(src, 16));
write("favicon-32.png", png(src, 32));
write("apple-touch-icon.png", png(src, 180));
write("icon-192.png", png(src, 192));
write("icon-512.png", png(src, 512));
write("icon-maskable-192.png", png(maskable, 192));
write("icon-maskable-512.png", png(maskable, 512));
