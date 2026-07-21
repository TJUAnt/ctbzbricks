import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget =
  process.env.BACKEND_URL ??
  `http://${process.env.BACKEND_HOST ?? '127.0.0.1'}:${process.env.BACKEND_PORT ?? '8000'}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        proxyTimeout: 60_000,
        timeout: 60_000,
      },
    },
  },
});
