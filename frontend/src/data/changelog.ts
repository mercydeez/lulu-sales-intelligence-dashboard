/**
 * In-app changelog (CX trust loop — docs/product/CX_LOOPS_PLAN.md Y3).
 * Newest first. Every entry is user-visible product change, not plumbing —
 * write for a store manager, not a code reviewer. The what's-new panel keys
 * its unread dot off the first entry's id, so give each release a unique id.
 *
 * Convention: prepend a new entry in the same PR that ships the feature.
 */
export interface ChangelogEntry {
  id: string;          // unique, e.g. '2026-07-07-dark-mode'
  date: string;        // ISO date shown to users
  title: string;
  tag: 'new' | 'improved' | 'fixed';
  items: string[];
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    id: '2026-07-07-cx-loops',
    date: '2026-07-07',
    title: 'Plan usage meters & system status',
    tag: 'new',
    items: [
      'Billing now shows live usage against your plan limits for the current period.',
      'A public system-status page shows real component health at /status.',
      'This "What\'s new" panel — release notes without leaving the app.',
    ],
  },
  {
    id: '2026-07-07-dark-mode',
    date: '2026-07-07',
    title: 'Dark mode',
    tag: 'new',
    items: [
      'Full dark theme across every screen and chart — near-black, low glare.',
      'Light / Dark / System control in the top bar and in Preferences; System follows your device automatically.',
    ],
  },
  {
    id: '2026-07-07-arabic-login',
    date: '2026-07-07',
    title: 'Arabic on the sign-in screen',
    tag: 'improved',
    items: [
      'The whole sign-in experience is now available in Arabic with right-to-left layout.',
      'Switch language directly on the sign-in screen — no account needed.',
    ],
  },
  {
    id: '2026-07-07-print-exports',
    date: '2026-07-07',
    title: 'Crisper report exports',
    tag: 'improved',
    items: [
      'Analytics and Reports exports are now print-quality documents with selectable text — use "Save as PDF" in the print dialog.',
      'Every export carries its methodology line, so figures are always traceable.',
    ],
  },
];
