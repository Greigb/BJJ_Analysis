import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      // Uploaded videos live at /assets/<id>/source.mp4 on the FastAPI backend;
      // without this proxy, the <video> element in /review/[id] 404s in dev mode.
      '/assets': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  resolve: {
    // Needed so Vitest picks the browser exports of Svelte 5 in jsdom tests.
    conditions: ['browser']
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['./tests/**/*.test.ts']
  }
});
