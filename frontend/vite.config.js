import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Output queda en frontend/dist/ por default; el Dockerfile multi-stage
  // de la raíz lo copia a /app/static durante el build de producción.
  server: {
    proxy: {
      '/api': 'http://localhost:8001'
    }
  }
})
