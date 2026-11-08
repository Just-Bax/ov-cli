import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const DEFAULT_API_PORT = 5180
const DEV_PORT = 5179
const API_PORT = Number(process.env.OV_AGENT_PORT ?? DEFAULT_API_PORT)
const SAME_CSS_ON_EVERY_OS = { optimize: false }
const PYTHON_PACKAGE_STATIC = path.resolve(import.meta.dirname, '../src/ov/agent/static')

export default defineConfig({
  plugins: [react(), tailwindcss(SAME_CSS_ON_EVERY_OS)],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
      '@shared': path.resolve(import.meta.dirname, 'shared'),
    },
  },
  build: {
    cssMinify: false,
    outDir: PYTHON_PACKAGE_STATIC,
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: DEV_PORT,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true },
    },
  },
})
