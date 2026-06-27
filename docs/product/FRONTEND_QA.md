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

## Current coverage (starting point)
- `src/lib/formatters.test.ts` — guards the **units-vs-AED** honesty convention
  (value→AED code, volume→unit label, K/M/B compaction).
- `src/app/accept-invite/page.test.tsx` — renders the invalid-link/empty state.
- `e2e/smoke.spec.ts` — login renders; accept-invite / reset-password show their
  no-token states.

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
