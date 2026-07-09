# Frontend QA

## Tooling (added Phase 10)
- **Unit/component:** Vitest + React Testing Library (jsdom). `npm test`
  (`vitest run`), `npm run test:watch`. Config: `frontend/vitest.config.ts`,
  setup `frontend/src/test/setup.ts`.
- **E2E:** Playwright. `npm run test:e2e`. Config `frontend/playwright.config.ts`,
  specs in `frontend/e2e/`. One-time setup (kept out of the default install):
  `npm i -D @playwright/test && npx playwright install --with-deps chromium`,
  then run against a running app: `E2E_BASE_URL=http://localhost:3000 npm run test:e2e`.
- **Typecheck/build gates:** `npx tsc --noEmit` and `npm run build` (both green).
  Test files live under `src/**/*.test.tsx`; `e2e/` is excluded from tsc.
- **Accessibility (E4-8):** axe-core over core routes in both themes.
  `npm run test:a11y` (spec: `frontend/e2e/a11y.spec.ts`). Same opt-in setup as
  E2E plus `npm i -D @axe-core/playwright`. Gate: **critical** violations fail;
  serious-and-below are logged (ratchet the gate to `serious` once the log is
  clean). Demo login overridable via `E2E_DEMO_EMAIL` / `E2E_DEMO_PASSWORD`.

  **CI handoff (Krishna — `.github/workflows/ci.yml` is yours):** after the
  existing frontend build step, boot the app and append:
  ```yaml
  - name: a11y (axe) scan
    working-directory: frontend
    run: |
      npm i -D @playwright/test @axe-core/playwright
      npx playwright install --with-deps chromium
      npm run test:a11y
    env:
      E2E_BASE_URL: http://localhost:3000
  ```

## Current coverage (starting point)
- `src/lib/formatters.test.ts` — guards the **units-vs-AED** honesty convention
  (value→AED code, volume→unit label, K/M/B compaction).
- `src/app/accept-invite/page.test.tsx` — renders the invalid-link/empty state.
- `e2e/smoke.spec.ts` — login renders; accept-invite / reset-password show their
  no-token states.
- `e2e/a11y.spec.ts` — axe scans: public routes, six authenticated routes, and
  dark-mode passes on `/login` + dashboard (theme seeded via `localStorage.theme`).
- `e2e/render-smoke.spec.ts` — **blank-tab regression guard.** Logs in as
  super_admin + regional_manager and navigates every one of the 21 sidebar
  routes, asserting the `<main>` region paints >40 chars of visible text. This
  catches pages that render blank (thrown render, failed JS chunk, or a render
  gated on data/config that never arrives) — which a 200-endpoint check cannot
  see. `npm run test:render` (needs the opt-in Playwright install). **Every nav
  page must have a `<main>` landmark** — the test enforces it (also an a11y
  requirement). Deploy-time blanks (stale chunk hashes after a redeploy) are
  additionally handled at runtime by `components/ChunkLoadRecovery.tsx`, which
  reloads once on a `ChunkLoadError`.

This is a foundation, not full coverage. Prioritized next specs: login → dashboard,
2FA, report export, security/audit page, Sage answer, EN/AR + RTL, SSE-degraded banner.

## Page-state checklist (every major page)
Loading · empty · error + retry · forbidden/unauthorized · **demo/sample data label
where applicable** · data freshness. The auth pages (`/login`, `/reset-password`,
`/verify-email`, `/accept-invite`) handle missing/invalid tokens with explicit
error states.

## How to add a test
- Pure logic → a `*.test.ts` next to the module (no DOM).
- Component → `*.test.tsx`; mock `next/navigation` hooks (see the accept-invite
  test). Avoid network — mock `fetch`/the api client.
- Flow → a Playwright spec in `e2e/` against a running app.
