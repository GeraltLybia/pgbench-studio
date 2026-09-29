import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests against a running compose stack (`docker compose up -d --build` from the
 * repository root, `server.dev_mode: true`). Credentials come from the environment, see
 * tests/e2e/env.ts.
 */
export default defineConfig({
  testDir: 'tests/e2e',
  // One stack, one agent: runs are sequential by nature.
  workers: 1,
  fullyParallel: false,
  timeout: 5 * 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } }],
})
