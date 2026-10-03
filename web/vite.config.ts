import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API_PORT = Number(process.env.OV_AGENT_PORT ?? 5180)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
      '@shared': path.resolve(import.meta.dirname, 'shared'),
    },
  },
  build: {
    // Shipped inside the Python package, so `ov agent` needs no Node at runtime.
    outDir: path.resolve(import.meta.dirname, '../src/ov/agent/static'),
    emptyOutDir: true,
  },
  server: {
    port: 5179,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true },
    },
  },
})
