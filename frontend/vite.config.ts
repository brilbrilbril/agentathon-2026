import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind all interfaces so the app is reachable from another device on the
    // same network, not just from this machine.
    host: true,
    port: 5173,
  },
})
