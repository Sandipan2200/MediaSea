import { defineConfig } from "vite";
import { resolve } from "node:path";

// Vanilla MV3 build: popup.html + popup.ts bundled to dist/ with stable names
// so manifest.json can reference them. No remote code, no eval — everything
// ships inside the package (MV3 code-readability requirement).
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: resolve(__dirname, "src/popup.html"),
      },
    },
  },
  publicDir: "public",
});
