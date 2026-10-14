import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Override for side-by-side instances (e.g. a QA backend on another port).
const apiTarget = process.env.REWINDSAFE_API_TARGET ?? 'http://127.0.0.1:8020'
const uiPort = Number(process.env.REWINDSAFE_UI_PORT ?? 5173)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: uiPort,
    strictPort: true,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: false,
        // Server-sent events must not be buffered or compressed by the dev proxy.
        configure: (proxy) => {
          proxy.on('proxyRes', (res) => {
            if (String(res.headers['content-type'] ?? '').includes('text/event-stream')) {
              res.headers['cache-control'] = 'no-cache'
              res.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
  build: { chunkSizeWarningLimit: 700 },
})
