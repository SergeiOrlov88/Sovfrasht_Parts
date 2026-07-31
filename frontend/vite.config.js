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
        background_color: '#0f172a',
        theme_color: '#0f172a',
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
})
