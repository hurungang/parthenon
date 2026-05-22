import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: {
    // Keep generated Pages artifacts under docs/ without replacing project documentation.
    outDir: '../docs/site',
    emptyOutDir: true,
  },
});
