/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const API = process.env.VITE_API_BASE || 'http://localhost:8050'
const PATHS = ['/chat', '/graph', '/consolidate', '/audit', '/health', '/sessions', '/memory', '/eval', '/insights']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      ...Object.fromEntries(
        PATHS.map((p) => [p, { target: API, changeOrigin: true }]),
      ),
      // Voice WebSocket — needs ws upgrade proxied to the FastAPI backend.
      '/voice': { target: API, changeOrigin: true, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
