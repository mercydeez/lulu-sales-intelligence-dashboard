import { test, expect, Page } from '@playwright/test';

/**
 * E0-5 — an XSS cannot exfiltrate the session at rest.
 *
 * After a full UI login, the access/refresh tokens must live ONLY in httpOnly
 * cookies (invisible to JavaScript). This asserts the property a real XSS payload
 * would exploit: nothing token-shaped is readable from localStorage,
 * sessionStorage, or document.cookie. The only JS-visible cookie is the CSRF
 * double-submit token, which is not a credential on its own.
 */

const DEMO_PASSWORD = 'Demo@2026!';
const DEMO_EMAIL = 'krishna@retaildemo.app';

// A JWT is three base64url segments separated by dots.
const JWT_RE = /\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/;

async function login(page: Page, email: string) {
  for (let i = 1; i <= 3; i++) {
    await page.goto('/login');
    await page.locator('#email').fill(email);
    await page.locator('#password').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    try {
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15_000 });
      return;
    } catch (e) {
      if (i === 3) throw e;
      await page.waitForTimeout(2_000 * i);
    }
  }
}

test('logged-in session exposes no token to JavaScript (E0-5)', async ({ page }) => {
  await login(page, DEMO_EMAIL);

  const snapshot = await page.evaluate(() => {
    const dump = (s: Storage) =>
      Object.fromEntries(Object.keys(s).map((k) => [k, s.getItem(k) ?? '']));
    return {
      localStorage: dump(window.localStorage),
      sessionStorage: dump(window.sessionStorage),
      cookie: document.cookie,
    };
  });

  // The two legacy token keys are gone (or at least hold no token).
  expect(snapshot.localStorage['app_access_token'] ?? null).toBeNull();
  expect(snapshot.localStorage['app_refresh_token'] ?? null).toBeNull();

  // Nothing JS can read looks like a JWT.
  const allValues = [
    ...Object.values(snapshot.localStorage),
    ...Object.values(snapshot.sessionStorage),
    snapshot.cookie,
  ].join('\n');
  expect(allValues).not.toMatch(JWT_RE);

  // The access/refresh cookies are httpOnly, so they never appear in document.cookie.
  expect(snapshot.cookie).not.toContain('access_token=');
  expect(snapshot.cookie).not.toContain('refresh_token=');

  // The profile IS in localStorage (needed for cache scoping, E0-6) but carries
  // no credential material.
  const profile = snapshot.localStorage['app_user'];
  expect(profile, 'profile should be present for cache scoping').toBeTruthy();
  expect(profile).not.toMatch(/token|password|secret/i);
});

test('the session still works — an authed page paints via the cookie', async ({ page }) => {
  await login(page, DEMO_EMAIL);
  // Proves the cookie transport actually authenticates (not just that tokens are
  // absent): a data page renders its heading from an authed API call.
  await page.goto('/analytics');
  await expect(page.getByText(/Analytics & Forecasting/i)).toBeVisible({ timeout: 20_000 });
});
