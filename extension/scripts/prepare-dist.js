// Post-build: copy manifest.json into dist/ and point default_popup at the
// emitted HTML. `node scripts/prepare-dist.js --store` additionally:
//   1. strips the localhost dev origin from host_permissions, and
//   2. FAILS THE BUILD (fail-closed) if any dev-network string
//      (localhost, 127.0.0.1, 0.0.0.0, :8000) survived into dist/.
// Store releases must be built with VITE_API_BASE set, e.g.
//   $env:VITE_API_BASE="https://api.mediasaver.example"; npm run build:store
import { globSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(root, "dist");
const store = process.argv.includes("--store");

const htmlFiles = globSync("**/popup.html", { cwd: dist });
if (htmlFiles.length === 0) {
  console.error("prepare-dist: no popup.html found in dist/");
  process.exit(1);
}
const popupPath = htmlFiles[0].replace(/\\/g, "/");

const manifest = JSON.parse(readFileSync(resolve(root, "manifest.json"), "utf8"));
manifest.action.default_popup = popupPath;
if (store) {
  manifest.host_permissions = (manifest.host_permissions ?? []).filter(
    (h) => !String(h).includes("localhost"),
  );
}
writeFileSync(resolve(dist, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log("dist manifest popup:", popupPath, "| store:", store);

if (store) {
  const suspects = /\blocalhost\b|127\.0\.0\.1|0\.0\.0\.0|:8000\b/;
  const hits = [];
  for (const f of globSync("**/*.{js,html,css,json}", { cwd: dist })) {
    const text = readFileSync(resolve(dist, f), "utf8");
    const m = text.match(suspects);
    if (m) hits.push(`${f}: matched ${JSON.stringify(m[0])}`);
  }
  if (hits.length > 0) {
    console.error("prepare-dist: dev-network strings leaked into store build:");
    for (const h of hits) console.error("  " + h);
    console.error("Rebuild with VITE_API_BASE set to the production API origin.");
    process.exit(1);
  }
  console.log("prepare-dist: no dev-network strings in store build. OK.");
}
