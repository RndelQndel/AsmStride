import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '../scripts',
  testMatch: 'generate_screenshots.spec.ts',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    browserName: 'chromium',
  },
  webServer: {
    command: '../.venv/bin/armstride --port 8765',
    url: 'http://127.0.0.1:8765',
    reuseExistingServer: false,
  },
});
