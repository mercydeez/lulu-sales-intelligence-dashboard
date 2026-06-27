# Accessibility

Target: WCAG 2.1 AA for the pilot. This is a checklist + current state, not a
certification claim.

## Principles
- **Semantic HTML + labels:** form inputs have associated labels/placeholders;
  buttons have discernible text. Icon-only controls need `aria-label`.
- **Keyboard:** every interactive element reachable and operable by keyboard; no
  keyboard traps; logical tab order.
- **Visible focus:** focus rings are present (Tailwind `focus:ring-*`) — do not
  remove them.
- **Color contrast:** text meets AA contrast on the surface/ink tokens; don't encode
  meaning by color alone (pair with text/icon).
- **Error messaging:** errors are text, near the field, not color-only.
- **Reduced motion:** respect `prefers-reduced-motion` for framer-motion animations.
- **RTL / i18n:** Arabic uses logical properties (`ps-*`/`pe-*`, `start`/`end`) so
  RTL mirrors correctly. Verify the dashboard and auth pages in EN and AR.

## Current state (honest)
- Auth pages use labelled inputs, visible focus rings, text error states, and logical
  (RTL-safe) spacing utilities.
- A full automated a11y audit (axe) and a screen-reader pass across all dashboard
  pages are **not yet done** — tracked in `MANUAL_CHECKS_REQUIRED.md`.

## How to check
- Keyboard-only walkthrough of: login, reset/accept-invite, dashboard, report export,
  Sage.
- Run axe (e.g. `@axe-core/playwright`) in the E2E smoke as a follow-up.
- Toggle OS reduced-motion and confirm animations soften/stop.
- Switch to Arabic and confirm layout mirrors and nothing clips.
