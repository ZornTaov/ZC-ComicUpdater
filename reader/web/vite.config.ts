import { defineConfig } from "vite";

// npm run dev serves the page here and hands /api to a reader started beside it with python -m comicreader
export default defineConfig({
  server: { proxy: { "/api": "http://localhost:8082" } },
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
});
