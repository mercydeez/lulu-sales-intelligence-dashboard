import { defineConfig, devices } from '@playwright/test';

// Smoke E2E config. Requires a one-time setup (not bundled — keeps the default
// install light):
//   npm i -D @playwright/test && npx playwright install --with-deps chromium
// Then run against a running app:
//   E2E_BASE_URL=http://localhost:3000 npm run test:e2e
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3000';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
