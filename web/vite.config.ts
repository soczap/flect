import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds straight into the Python package. server.py serves index.html at "/" and stamps
// /static/app.js and /static/app.css with their mtime, so those two names must stay fixed.
export default defineConfig({
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: path.resolve(__dirname, "../flect/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: (info) => (info.names?.some((n) => n.endsWith(".css")) ? "app.css" : "assets/[name]-[hash][extname]"),
      },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:1113" } },
});
