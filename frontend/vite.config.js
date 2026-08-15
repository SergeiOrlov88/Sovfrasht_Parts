import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Dev-сервер ходит в API через прокси — так фронтенд обращается к /api/v1
// одинаково и локально, и за Nginx в прод/тест.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Совфрахт Детали',
        short_name: 'Детали',
        description: 'Распознавание судовых деталей по фото',
        lang: 'ru',
        start_url: '/',
        display: 'standalone',
        background_color: '#0a1420',
        theme_color: '#0a1420',
      },
    }),
  ],
  server: {
    // Явная привязка к IPv4: по умолчанию Vite поднимается только на ::1,
    // и на части Windows-машин http://localhost:5173 тогда не открывается.
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
})
