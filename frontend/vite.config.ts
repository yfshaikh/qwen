import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend the dev proxy forwards to. In dev, the app calls same-origin paths
// (e.g. "/graph") and Vite proxies them here, so there is no CORS to configure.
// In production (Docker/nginx), the app calls VITE_API_BASE directly instead.
const API_TARGET = process.env.VITE_API_BASE || "http://localhost:8000";

// Endpoints the backend exposes; everything else is served by Vite (the SPA).
const API_PATHS = [
  "/graph",
  "/ingest",
  "/consolidate",
  "/recall",
  "/audit",
  "/tutor",
  "/health",
  "/llm-ping",
];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
});
