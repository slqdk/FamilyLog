/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// Dev server proxies the API to the backend on :8080.
// Two pages: the app (index.html) and FamilyMap's family page (fm/, served
// at /fm/). Both land in dist/, which the Dockerfile copies whole into
// backend/static.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8080' },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('./index.html', import.meta.url)),
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
