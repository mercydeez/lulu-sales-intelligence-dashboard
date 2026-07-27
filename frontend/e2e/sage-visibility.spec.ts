import { expect, test } from '@playwright/test';

const DEMO_EMAIL = 'atharva@retaildemo.app';
const DEMO_PASSWORD = 'Demo@2026!';

test('Sage is hidden when signed out and remains visible after login config loads', async ({ page }) => {
  await page.goto('/login');

  const sageLauncher = () => page.getByRole('button', { name: /^(Open )?Sage$/ });
  await expect(sageLauncher()).toHaveCount(0);

  await page.locator('#email').fill(DEMO_EMAIL);
  await page.locator('#password').fill(DEMO_PASSWORD);
  await page.getByRole('button', { name: /^sign in$/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 });

  const sageButton = sageLauncher();
  await expect(sageButton).toBeVisible();

  // The experience request resolves after the authenticated shell paints. The
  // launcher must remain present regardless of assistant_mode in that payload.
  await page.waitForTimeout(4_000);
  await expect(sageButton).toBeVisible();
});
