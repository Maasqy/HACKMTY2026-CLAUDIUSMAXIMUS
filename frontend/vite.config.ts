import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// public/ mirrors pipeline output for both dev and prod builds.
// Refresh with: scripts/refresh_frontend_snapshots.sh (or the ps1 equivalent).
export default defineConfig({
  root: __dirname,
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: { port: 5173, strictPort: false },
  build: { outDir: "dist", sourcemap: true },
});
