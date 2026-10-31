import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const here = path.dirname(fileURLToPath(import.meta.url));

// Strict CSP for built pages. ponytail: dev has none because Vite's HMR preamble is an inline script.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  'connect-src http://127.0.0.1:*',
  'frame-src http://127.0.0.1:*',
  "worker-src 'self'",
  "font-src 'self' data:",
  "img-src 'self' data:",
  "object-src 'none'",
  "base-uri 'none'",
].join('; ');

const cspMeta = {
  name: 'klaro-csp',
  apply: 'build',
  transformIndexHtml: () => [
    { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: CSP }, injectTo: 'head-prepend' },
  ],
};

export default defineConfig({
  root: path.join(here, 'renderer'),
  base: './',
  plugins: [react(), cspMeta],
  build: { outDir: path.join(here, 'dist'), emptyOutDir: true },
});
