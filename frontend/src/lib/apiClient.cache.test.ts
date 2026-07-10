import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { apiRequest, clearApiCache } from './apiClient';

// E0-6: the response cache must never serve data across an authorization boundary.
// The backend scopes every response by (tenant, role, accessible stores/regions).
// Keying the cache on user id alone let a role switch — which keeps `id` constant —
// read back the privileged answer fetched under the previous role.

const USER_KEY = 'app_user';
const TTL = 60_000;

interface StoredUser {
  id: number;
  tenant_id?: number;
  role?: string;
  accessible_stores?: number[];
  accessible_regions?: string[];
}

function signIn(user: StoredUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/** Mock fetch that returns a different body on each call, so a cache hit is visible. */
function mockSequentialFetch(bodies: unknown[]): ReturnType<typeof vi.fn> {
  let call = 0;
  const fetchMock = vi.fn(async () => {
    const body = bodies[Math.min(call, bodies.length - 1)];
    call += 1;
    return {
      ok: true,
      status: 200,
      json: async () => body,
    } as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const SUPER_ADMIN: StoredUser = {
  id: 1,
  tenant_id: 1,
  role: 'super_admin',
  accessible_stores: [1, 2, 3, 4, 5],
};

// Same person, same id — demoted to a single store.
const DEMOTED: StoredUser = {
  id: 1,
  tenant_id: 1,
  role: 'store_manager',
  accessible_stores: [1],
};

beforeEach(() => {
  localStorage.clear();
  clearApiCache();
  // Give the client a CSRF token so ensureCsrfToken() doesn't fire an extra
  // bootstrap GET on mutations (E0-5) — these tests assert cache behaviour, not
  // the CSRF handshake, so we isolate them from it.
  document.cookie = 'csrf_token=test-csrf';
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('apiClient cache — authorization scoping', () => {
  it('serves a cache hit for the same identity and url', async () => {
    signIn(SUPER_ADMIN);
    const fetchMock = mockSequentialFetch([{ revenue: 999 }, { revenue: 111 }]);

    const first = await apiRequest('/api/kpis', { ttl: TTL });
    const second = await apiRequest('/api/kpis', { ttl: TTL });

    expect(first).toEqual({ revenue: 999 });
    expect(second).toEqual({ revenue: 999 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never serves a privileged response after a role switch in the same tab', async () => {
    signIn(SUPER_ADMIN);
    const fetchMock = mockSequentialFetch([
      { revenue: 5_000_000 }, // all 5 stores — super_admin's view
      { revenue: 200_000 },   // one store — store_manager's view
    ]);

    const asAdmin = await apiRequest('/api/kpis', { ttl: TTL });
    expect(asAdmin).toEqual({ revenue: 5_000_000 });

    // Role switch: same user id, narrower scope. The old key must not match.
    signIn(DEMOTED);
    const asManager = await apiRequest('/api/kpis', { ttl: TTL });

    expect(asManager).toEqual({ revenue: 200_000 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('never serves one tenant a response cached for another', async () => {
    signIn({ id: 1, tenant_id: 1, role: 'analyst' });
    const fetchMock = mockSequentialFetch([{ tenant: 'meridian' }, { tenant: 'acme' }]);

    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ tenant: 'meridian' });

    signIn({ id: 1, tenant_id: 2, role: 'analyst' });
    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ tenant: 'acme' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('re-fetches when a store grant is revoked, even with role and tenant unchanged', async () => {
    signIn({ id: 3, tenant_id: 1, role: 'regional_manager', accessible_stores: [1, 2] });
    const fetchMock = mockSequentialFetch([{ stores: 2 }, { stores: 1 }]);

    expect(await apiRequest('/api/sales', { ttl: TTL })).toEqual({ stores: 2 });

    signIn({ id: 3, tenant_id: 1, role: 'regional_manager', accessible_stores: [1] });
    expect(await apiRequest('/api/sales', { ttl: TTL })).toEqual({ stores: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('treats store order as insignificant, so an identical scope still hits cache', async () => {
    signIn({ id: 4, tenant_id: 1, role: 'analyst', accessible_stores: [3, 1, 2] });
    const fetchMock = mockSequentialFetch([{ ok: true }, { ok: false }]);

    await apiRequest('/api/kpis', { ttl: TTL });

    signIn({ id: 4, tenant_id: 1, role: 'analyst', accessible_stores: [1, 2, 3] });
    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reads the scope from permissions when it is nested there', async () => {
    localStorage.setItem(
      USER_KEY,
      JSON.stringify({ id: 5, tenant_id: 1, role: 'analyst', permissions: { accessible_stores: [1] } }),
    );
    const fetchMock = mockSequentialFetch([{ v: 1 }, { v: 2 }]);
    await apiRequest('/api/kpis', { ttl: TTL });

    localStorage.setItem(
      USER_KEY,
      JSON.stringify({ id: 5, tenant_id: 1, role: 'analyst', permissions: { accessible_stores: [1, 2] } }),
    );
    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ v: 2 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not cache an anonymous response under a logged-in identity', async () => {
    const fetchMock = mockSequentialFetch([{ anon: true }, { anon: false }]);

    await apiRequest('/api/kpis', { ttl: TTL }); // no user in storage

    signIn(SUPER_ADMIN);
    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ anon: false });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('flushes the previous identity\'s entries on switch, so a revert starts cold', async () => {
    signIn(SUPER_ADMIN);
    const fetchMock = mockSequentialFetch([{ n: 1 }, { n: 2 }, { n: 3 }]);

    await apiRequest('/api/kpis', { ttl: TTL }); // cached under super_admin

    signIn(DEMOTED);
    await apiRequest('/api/kpis', { ttl: TTL }); // flushes, caches under store_manager

    signIn(SUPER_ADMIN); // revert — must NOT replay the pre-switch entry
    expect(await apiRequest('/api/kpis', { ttl: TTL })).toEqual({ n: 3 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('does not cache non-GET requests', async () => {
    signIn(SUPER_ADMIN);
    const fetchMock = mockSequentialFetch([{ n: 1 }, { n: 2 }]);

    await apiRequest('/api/kpis', { ttl: TTL, method: 'POST', body: {} });
    await apiRequest('/api/kpis', { ttl: TTL, method: 'POST', body: {} });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
