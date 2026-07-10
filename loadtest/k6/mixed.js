// E6-5 — the dashboard read mix under load.
//
// Runs the endpoints a signed-in user actually hits while looking at the product:
// KPI cards, the analytics summary and trend, sales history, and the public
// version-discovery endpoint (unauthenticated, so it also proves the open surface
// stays open under load).
//
// AUTH. The product uses httpOnly cookies, so `setup()` logs in once and hands the
// Set-Cookie header to every VU. Logging in per iteration would measure bcrypt,
// not the dashboard.
//
// RATE LIMITS. All VUs share one source IP, so the per-IP bucket (100/min by
// default) would reject almost everything and we would be load-testing the rate
// limiter. Run the stack with RATE_LIMIT_REQUESTS raised — see
// docs/production/LOAD_TEST_BASELINE.md. A 429 is therefore a FAILURE here, not a
// success: it means the harness was misconfigured.
import http from 'k6/http';
import exec from 'k6/execution';
import { check, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE_URL || 'http://backend:8000';
const EMAIL = __ENV.LOGIN_EMAIL || 'atharva@retaildemo.app';
const PASSWORD = __ENV.LOGIN_PASSWORD || 'Demo@2026!';

const errors = new Rate('business_errors');
const rateLimited = new Rate('rate_limited');
const kpiLatency = new Trend('kpi_latency', true);
const analyticsLatency = new Trend('analytics_latency', true);
const sageLatency = new Trend('sage_latency', true);

// Sage is asked on one iteration in `SAGE_EVERY`. It is a grounded, rule-based
// answer (no LLM configured in this environment), so this measures OUR query
// path, not somebody's inference server. Asking on every iteration would make the
// mix a Sage benchmark rather than a dashboard one.
//
// CAUTION, and a trap we walked into. uvicorn's keep-alive is 5s. At SAGE_EVERY=5
// and ~6s iterations, a VU's connection sits idle ~30s between Sage calls, so the
// server closes it and k6 reuses the corpse: `Post ...: EOF`, ~70% of Sage
// requests, with nothing in the server log. That is a HARNESS artifact — real
// browsers and every HTTP client with retry-on-idempotent-reuse do not see it.
// Setting SAGE_EVERY=1 keeps the connection warm and the failures vanish.
// If you raise SAGE_EVERY again, expect EOFs and do not read them as capacity.
const SAGE_EVERY = Number(__ENV.SAGE_EVERY || 1);

export const options = {
  scenarios: {
    dashboard_mix: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '20s', target: 100 },  // ramp to the target concurrency
        { duration: '60s', target: 100 },  // hold — this is the measured window
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    // Deliberately loose. This is a BASELINE to detect regression, not a promise
    // of production performance on production hardware. See the doc.
    http_req_failed: ['rate<0.01'],
    rate_limited: ['rate<0.01'],
    business_errors: ['rate<0.01'],
    'http_req_duration{expected_response:true}': ['p(95)<2000'],
  },
};

export function setup() {
  // A safe request issues the csrf_token cookie; state-changing requests must
  // echo it back in X-CSRF-Token (double submit). Same flow a browser walks.
  const seed = http.get(`${BASE}/api/auth/me`);
  const csrf = seed.cookies['csrf_token'] ? seed.cookies['csrf_token'][0].value : null;
  if (!csrf) throw new Error('setup(): no csrf_token cookie issued');

  const res = http.post(
    `${BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, Cookie: `csrf_token=${csrf}` } },
  );
  if (res.status !== 200) {
    throw new Error(`setup(): login failed with ${res.status} — ${res.body}`);
  }
  // Reuse the raw cookie header rather than k6's per-VU jar, which setup() cannot
  // populate for other VUs.
  const jar = { csrf_token: csrf };
  Object.keys(res.cookies).forEach((name) => { jar[name] = res.cookies[name][0].value; });
  const header = Object.keys(jar).map((n) => `${n}=${jar[n]}`).join('; ');
  return { cookie: header, csrf };
}

function authed(data) {
  return { headers: { Cookie: data.cookie }, tags: {} };
}

function authedPost(data) {
  return {
    headers: {
      Cookie: data.cookie,
      'Content-Type': 'application/json',
      'X-CSRF-Token': data.csrf,
    },
  };
}

export default function (data) {
  const params = authed(data);

  group('kpis', () => {
    const r = http.get(`${BASE}/api/kpis`, params);
    kpiLatency.add(r.timings.duration);
    rateLimited.add(r.status === 429);
    errors.add(r.status >= 400);
    check(r, { 'kpis 200': (x) => x.status === 200 });
  });

  group('analytics', () => {
    const r1 = http.get(`${BASE}/api/analytics/summary`, params);
    const r2 = http.get(`${BASE}/api/analytics/trend?days=30`, params);
    analyticsLatency.add(r1.timings.duration);
    analyticsLatency.add(r2.timings.duration);
    [r1, r2].forEach((r) => {
      rateLimited.add(r.status === 429);
      errors.add(r.status >= 400);
    });
    check(r1, { 'analytics summary 200': (x) => x.status === 200 });
    check(r2, { 'analytics trend 200': (x) => x.status === 200 });
  });

  group('history', () => {
    const r = http.get(`${BASE}/api/history?limit=50`, params);
    rateLimited.add(r.status === 429);
    errors.add(r.status >= 400);
    check(r, { 'history 200': (x) => x.status === 200 });
  });

  group('public_discovery', () => {
    // Unauthenticated on purpose: it must answer even when everything else is busy.
    const r = http.get(`${BASE}/api/public/versions`);
    errors.add(r.status >= 400);
    check(r, { 'versions 200': (x) => x.status === 200 });
  });

  // SAGE_EVERY=0 disables Sage entirely. Spelled out, because relying on
  // `n % 0 === NaN` being falsy is a coincidence, not an intention.
  if (SAGE_EVERY > 0 && exec.scenario.iterationInTest % SAGE_EVERY === 0) {
    group('sage', () => {
      const r = http.post(
        `${BASE}/api/ai/chat`,
        JSON.stringify({ message: 'What were total sales last week?', stream: false }),
        authedPost(data),
      );
      sageLatency.add(r.timings.duration);
      rateLimited.add(r.status === 429);
      errors.add(r.status >= 400);
      check(r, { 'sage 200': (x) => x.status === 200 });
    });
  }
}
