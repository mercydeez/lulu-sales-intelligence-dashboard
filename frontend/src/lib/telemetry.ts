/**
 * Product telemetry substrate (CX measurement loop — see docs/product/CX_LOOPS_PLAN.md).
 *
 * Vendor-agnostic by design: call sites use the typed `track()` API and never
 * know the sink. Today the sink is PostHog EU cloud, loaded lazily via its
 * remote snippet ONLY when `NEXT_PUBLIC_POSTHOG_KEY` is set — with no key
 * (dev, demo, self-host-averse tenants) every call is a silent no-op. The
 * planned first-party ingest (`POST /api/telemetry/events`, Krishna K1) slots
 * in behind the same interface with zero call-site churn.
 *
 * Scale/CX rules enforced here:
 *  - never block an interaction: the SDK loads after first paint, and events
 *    tracked before it arrives ride PostHog's own stub queue
 *  - no PII in identity or props: user id / tenant id / role only
 *  - error reporting is throttled (max 10/session) so a render loop can't
 *    turn telemetry into a DoS on ourselves
 *  - autocapture and session recording are OFF — explicit events only, which
 *    keeps the PDPL surface reviewable
 */

// The activation funnel + core actions. Add events here (typed) — never pass
// free-form strings at call sites.
export type TelemetryEvent =
  | 'page_viewed'
  | 'login_succeeded'
  | 'login_2fa_succeeded'
  | 'onboarding_step_clicked'
  | 'import_cta_clicked'
  | 'export_printed'
  | 'theme_changed'
  | 'lang_changed'
  | 'whats_new_opened'
  | 'usage_meters_viewed'
  | 'upgrade_cta_clicked'
  | 'status_page_viewed'
  | 'exec_mode_toggled'
  | 'sage_nudge_clicked'
  | 'feedback_submitted'
  | 'nps_submitted'
  | 'client_error';

type Props = Record<string, string | number | boolean | null | undefined>;

const KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://eu.i.posthog.com';

const enabled = () => typeof window !== 'undefined' && !!KEY;

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    posthog?: any;
  }
}

let loaded = false;
let errorCount = 0;
const MAX_ERRORS_PER_SESSION = 10;

/** Inject PostHog's stub + script. The stub queues calls until the script
 *  arrives, so `track()` is safe to call immediately after init(). */
function loadSnippet() {
  if (loaded || !enabled()) return;
  loaded = true;
  const w = window as any;
  // Official loader stub (condensed): queue method calls on an array until
  // the real library replaces them.
  w.posthog = w.posthog || [];
  const ph = w.posthog;
  if (ph.__SV) return; // already initialised by another bundle
  ph._i = [];
  ph.init = function (key: string, config: any, name?: string) {
    const stub = (obj: any, method: string) => {
      obj[method] = function (...args: any[]) {
        obj.push([method, ...args]);
      };
    };
    const inst: any = ph;
    inst.people = inst.people || [];
    inst.toString = () => 'posthog (stub)';
    [
      'capture', 'identify', 'alias', 'people.set', 'people.set_once', 'set_config',
      'register', 'register_once', 'unregister', 'opt_out_capturing', 'has_opted_out_capturing',
      'opt_in_capturing', 'reset', 'isFeatureEnabled', 'onFeatureFlags', 'getFeatureFlag',
      'getFeatureFlagPayload', 'group',
    ].forEach((m) => {
      if (m.indexOf('people.') === 0) stub(inst.people, m.split('.')[1]);
      else stub(inst, m);
    });
    ph._i.push([key, config, name]);
  };
  ph.__SV = 1;
  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.async = true;
  script.src = `${HOST.replace(/\/$/, '')}/static/array.js`;
  document.head.appendChild(script);

  ph.init(KEY, {
    api_host: HOST,
    autocapture: false,             // explicit events only (PDPL-reviewable)
    capture_pageview: false,        // we send page_viewed ourselves (SPA-correct)
    disable_session_recording: true,
    persistence: 'localStorage',
  });
}

/** Initialise the pipeline (idempotent). Call once after first paint. */
export function initTelemetry() {
  if (!enabled()) return;
  loadSnippet();

  // Client-error reporting through the same pipe, throttled.
  window.addEventListener('error', (e) => {
    trackError(e.message, e.filename || 'window.onerror');
  });
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason instanceof Error ? e.reason.message : String(e.reason);
    trackError(reason, 'unhandledrejection');
  });
}

/** Record a product event. No-op without a key; safe pre-load (stub queues). */
export function track(event: TelemetryEvent, props?: Props) {
  if (!enabled()) {
    if (process.env.NODE_ENV === 'development' && typeof console !== 'undefined') {
      console.debug('[telemetry:noop]', event, props ?? {});
    }
    return;
  }
  try {
    window.posthog?.capture(event, props);
  } catch {
    /* telemetry must never break the app */
  }
}

/** Bind the session to ids ONLY — no names or emails ever. */
export function identify(userId: number | string, meta: { tenant_id?: number | string; role?: string }) {
  if (!enabled()) return;
  try {
    window.posthog?.identify(String(userId), { tenant_id: meta.tenant_id, role: meta.role });
    if (meta.tenant_id != null) window.posthog?.group('tenant', String(meta.tenant_id));
  } catch { /* ignore */ }
}

/** Unbind on logout so the next login isn't cross-linked. */
export function resetIdentity() {
  if (!enabled()) return;
  try {
    window.posthog?.reset();
  } catch { /* ignore */ }
}

function trackError(message: string, source: string) {
  if (errorCount >= MAX_ERRORS_PER_SESSION) return;
  errorCount += 1;
  track('client_error', { message: message.slice(0, 300), source });
}
