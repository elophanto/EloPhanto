import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['src/server.ts'],
  format: ['esm'],
  dts: false,
  clean: true,
  sourcemap: true,
  target: 'node20',
  external: [
    'playwright',
    'playwright-extra',
    'puppeteer-extra-plugin-stealth',
    'sharp',
  ],
});
