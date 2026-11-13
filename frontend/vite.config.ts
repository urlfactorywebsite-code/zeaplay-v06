import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '');
    const apiBaseUrl = env.VITE_API_BASE_URL || '/api';
    const devProxyTarget =
      env.VITE_API_PROXY_TARGET ||
      (apiBaseUrl.startsWith('http') ? apiBaseUrl : 'http://localhost:7211');

    return {
      server: {
        port: 7300,
        host: '0.0.0.0',
        proxy: {
          '/api': {
            target: devProxyTarget,
            changeOrigin: true,
            ws: true,
            rewrite: (path) => path,
          },
        },
      },
      plugins: [react(), {
        name: 'private-provider-credentials',
        configResolved(config) {
          // VITE_ values are public, including when code reads the entire env
          // object. Exclude legacy credential variables from every client build.
          for (const key of Object.keys(config.env)) {
            if (/GEMINI_API_KEY/.test(key)) delete config.env[key];
          }
        },
      }],
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});
