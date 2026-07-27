import { test, expect } from '@playwright/test';

// Smoke E2E — verifies the app loads and core public pages render their states.
// Requires a running app (E2E_BASE_URL) and a one-time Playwright install; see
// playwright.config.ts. These are intentionally light: deep flows (login, 2FA,
// import) are added as the pilot stabilizes.

test('login page renders', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('button')).toBeVisible();
});

test('accept-invite with no token shows an invalid-link state', async ({ page }) => {
  await page.goto('/accept-invite');
  await expect(page.getByText(/invalid invite link/i)).toBeVisible();
});

test('reset-password with no token shows an invalid-link state', async ({ page }) => {
  await page.goto('/reset-password');
  await expect(page.getByText(/invalid reset link/i)).toBeVisible();
});
