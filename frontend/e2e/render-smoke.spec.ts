import { test, expect, Page } from '@playwright/test';

/**
 * Render smoke (regression guard for the "blank tab" class of bug).
 *
 * Why this exists: API-level checks (endpoint returns 200) do NOT prove a page
 * actually PAINTS. A page can call a healthy API and still render blank if the
 * React tree throws, a JS chunk fails to load, or the whole render is gated on
 * data/config that never arrives. This spec navigates every sidebar route as a
 * real logged-in user and asserts the <main> region contains substantive
 * visible text — catching blank pages a 200-check misses.
 *
 * One-time setup (same opt-in convention as the a11y/smoke suites):
 *   npm i -D @playwright/test && npx playwright install --with-deps chromium
 * Run against a running app:
 *   E2E_BASE_URL=http://localhost:3000 npm run test:render
 *
 * Roles: runs the full nav for super_admin AND regional_manager (both now see
 * every tab). store_manager sees a curated subset — not asserted here.
 */

const DEMO_PASSWORD = process.env.E2E_DEMO_PASSWORD || 'Demo@2026!';

// Every route reachable from the full sidebar. If a page is added to
// config/nav.tsx, add it here too — that keeps this guard honest.
const ROUTES = [
  '/', '/briefing', '/decisions', '/inventory', '/promotions', '/procurement',
  '/approvals', '/value', '/analytics', '/insights', '/action-drafts',
  '/forecast-lab', '/uae-insights', '/employees', '/reports',
  '/admin', '/security', '/audit', '/data-sources', '/developers', '/monitoring',
];

// A rendered page always paints at least its header/title. Anything below this
// is effectively blank. Loading skeletons and empty states clear this bar.
const MIN_CONTENT_CHARS = 40;

async function login(page: Page, email: string) {
  // Retry the login itself: under parallel runs the shared per-IP rate limiter
  // can 429 a login burst, leaving the page on /login. That's transient — a
  // brief backoff drains the sliding window. This guards the SETUP only; the
  // per-page paint assertion below is never retried, so real blank pages still
  // fail loudly.
  const attempts = 3;
  for (let i = 1; i <= attempts; i++) {
    await page.goto('/login');
    await page.locator('#email').fill(email);
    await page.locator('#password').fill(DEMO_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();
    try {
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15_000 });
      return;
    } catch (e) {
      if (i === attempts) throw e;
      await page.waitForTimeout(2_000 * i); // linear backoff: 2s, 4s
    }
  }
}

async function assertRenders(page: Page, route: string) {
  await page.goto(route);
  // Key on the shell's stable content wrapper (AppShell renders
  // <div id="main-content">{page}</div>) rather than a per-page <main> — pages
  // vary in whether they wrap in <main> or <div>, and that's not what we're
  // testing. We're testing that the CONTENT AREA paints real text.
  const content = page.locator('#main-content');
  await expect(content, `${route}: no #main-content (shell didn't render)`).toBeVisible();
  // Poll until the content area paints text. Slow pages (Sage briefing, forecast
  // model metrics) resolve well after first paint; polling up to 12s handles
  // them without a flaky fixed wait, while a genuinely blank page still fails.
  await expect
    .poll(async () => ((await content.innerText()) || '').trim().length, {
      timeout: 12_000,
      message: `${route} rendered blank — #main-content never painted content`,
    })
    .toBeGreaterThan(MIN_CONTENT_CHARS);
}

for (const role of ['atharva@retaildemo.app', 'krishna@retaildemo.app']) {
  test.describe(`render smoke — ${role}`, () => {
    test.beforeEach(async ({ page }) => {
      await login(page, role);
    });
    for (const route of ROUTES) {
      test(`${route} paints content`, async ({ page }) => {
        await assertRenders(page, route);
      });
    }
  });
}
