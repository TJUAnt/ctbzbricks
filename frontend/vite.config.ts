import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget =
  process.env.BACKEND_URL ??
  `http://${process.env.BACKEND_HOST ?? '127.0.0.1'}:${process.env.BACKEND_PORT ?? '8000'}`;
const goBackendTarget =
  process.env.GO_BACKEND_URL ??
  `http://${process.env.GO_BACKEND_HOST ?? '127.0.0.1'}:${process.env.GO_BACKEND_PORT ?? '8080'}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/v1': {
        target: goBackendTarget,
        changeOrigin: true,
        proxyTimeout: 60_000,
        timeout: 60_000,
      },
      '/api': {
        target: backendTarget,
        changeOrigin: true,
        proxyTimeout: 60_000,
        timeout: 60_000,
      },
    },
  },
});
