/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// Dev server proxies the API to the backend on :8080.
// Three pages, all landing in dist/ (the Dockerfile copies it whole into
// backend/static):
//   /      the front page for the whole family (index.html - src/home)
//   /app/  the admin app: Økonomi, FamilyMap admin, Dagbog settings, Settings
//   /fm/   Alf's Atlas, FamilyMap's family page
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8080' },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        home: fileURLToPath(new URL('./index.html', import.meta.url)),
        app: fileURLToPath(new URL('./app/index.html', import.meta.url)),
        fm: fileURLToPath(new URL('./fm/index.html', import.meta.url)),
      },
    },
  },
  // Vitest: jsdom for component tests; setup adds the jest-dom matchers.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
