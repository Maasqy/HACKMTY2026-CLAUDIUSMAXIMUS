import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// publicDir apunta a la raiz del repo para servir /out y /eval como estaticos
// durante dev. Asi el front lee fetch("/out/submission.json") directamente
// sin proxy, symlink ni servidor Python.
export default defineConfig({
  root: __dirname,
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  publicDir: path.resolve(__dirname, ".."),
  server: {
    port: 5173,
    strictPort: false,
    fs: {
      allow: [path.resolve(__dirname, "..")],
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
