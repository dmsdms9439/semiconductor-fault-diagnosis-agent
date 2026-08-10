import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // REST API 프록시 — 개발 모드에서 CORS 회피
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // WebSocket 프록시
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
