import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// The dev proxy keeps the browser same-origin with the backend (no CORS, no mixed content).
const backend = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:41500'

// Production is served from a sub-path of the shared IIS site (e.g. /SmartRemoteAI/).
export default defineConfig(({ mode }) => ({
  base: loadEnv(mode, process.cwd(), 'VITE_').VITE_BASE ?? '/',
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'Smart Remote AI',
        short_name: 'Smart Remote',
        description: 'שלט אוניברסלי חכם ל-HOT ול-LG',
        lang: 'he',
        dir: 'rtl',
        display: 'standalone',
        orientation: 'any',
        background_color: '#080B16',
        theme_color: '#080B16',
        icons: [{ src: 'icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }],
      },
      // Offline shows the cached shell only; remote actions are never queued or faked.
      workbox: { navigateFallbackDenylist: [/^\/api/, /^\/ws/] },
    }),
  ],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: false },
      '/ws': { target: backend.replace('http', 'ws'), ws: true },
    },
  },
  test: { environment: 'node' },
}))
