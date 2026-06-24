/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API = process.env.VITE_API_BASE || 'http://localhost:8000'
const PATHS = ['/chat', '/graph', '/consolidate', '/audit', '/health']

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      PATHS.map((p) => [p, { target: API, changeOrigin: true }]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
