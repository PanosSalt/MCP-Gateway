import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/admin/',
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/auth': 'http://localhost:8000',
      '/tenants': 'http://localhost:8000',
      '/connections': 'http://localhost:8000',
      '/query': 'http://localhost:8000',
      '/api-keys': 'http://localhost:8000',
      '/audit-logs': 'http://localhost:8000',
      '/tools': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
