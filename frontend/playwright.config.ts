import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1,
  use: { baseURL: 'http://127.0.0.1:8765', browserName: 'chromium', trace: 'retain-on-failure' },
  webServer: {
    command: '../.venv/bin/armstride --port 8765',
    url: 'http://127.0.0.1:8765', reuseExistingServer: false,
  },
});
