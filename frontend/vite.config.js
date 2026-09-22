import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, /api is proxied to the FastAPI backend so the browser sees one origin (no CORS setup needed).
const API_TARGET = process.env.VITE_DEV_API_TARGET || "http://127.0.0.1:8000";
// Screen 6 (specs/screen-06-report-workflow.md) calls Camunda Tasklist's REST API directly from
// the browser, per CLAUDE.md's Workflow Engine Decision - Tasklist's self-managed image doesn't
// ship CORS headers for a cross-origin dev server, so /tasklist is proxied the same way /api is,
// rather than standing up CORS config on the Camunda side for a local POC.
const TASKLIST_TARGET = process.env.VITE_DEV_TASKLIST_TARGET || "http://127.0.0.1:8082";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/tasklist": { target: TASKLIST_TARGET, changeOrigin: true, rewrite: (path) => path.replace(/^\/tasklist/, "") },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    globals: true,
    css: false,
  },
});
