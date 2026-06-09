import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: API requests are proxied to the backend at http://localhost:8000
// (override with ENGRAM_API_TARGET). The frontend code calls relative paths
// like `/graph`, so no CORS setup is needed in development.
//
// Production: set VITE_API_BASE at build time (e.g.
// `VITE_API_BASE=https://api.example.com npm run build`, or
// `docker build --build-arg VITE_API_BASE=...`). When unset, the app keeps
// using relative paths, which works when the SPA is served behind the same
// origin / reverse proxy as the API.
const API_PATHS = [
  "/graph",
  "/evidence",
  "/ingest",
  "/consolidate",
  "/recall",
  "/audit",
  "/tutor",
  "/health",
  "/llm-ping",
];

const target = process.env.ENGRAM_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target, changeOrigin: true }]),
    ),
  },
});
