/**
 * Single frontend API client (Phase 2.7).
 *
 * One place for: base URL, httpOnly-COOKIE auth (E0-5 — no token ever touches
 * localStorage; the browser sends the httpOnly access/refresh cookies via
 * credentials:'include' and cannot read them, so an XSS can't exfiltrate them
 * at rest), CSRF double-submit on state-changing requests, 401 -> refresh ->
 * retry, an authorization-scoped response cache (keyed by user + tenant + role +
 * accessible stores/regions — GAP M2, E0-6), and parsing of the backend's JSON
 * error envelope into a typed ApiError (GAP M3).
 *
 * Auth endpoints (login/refresh/logout) stay in AuthContext; everything else
 * should go through here. `authFetch` is exposed for callers that need the raw
 * Response (e.g. streaming/blob); typed JSON callers use apiGet/apiPost/etc.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Only the user PROFILE is kept in localStorage (for cache scoping, E0-6). The
// access/refresh tokens are httpOnly cookies the browser manages — JS never
// reads or writes them. The two token keys remain here ONLY so clearSession can
// purge them from browsers that stored them before E0-5.
const LEGACY_ACCESS_TOKEN_KEY = 'app_access_token';
const LEGACY_REFRESH_TOKEN_KEY = 'app_refresh_token';
const USER_KEY = 'app_user';

// The double-submit CSRF pair: the backend sets a JS-readable `csrf_token` cookie
// on GET /api/* responses; we echo it back in this header on every mutation.
const CSRF_COOKIE = 'csrf_token';
const CSRF_HEADER = 'X-CSRF-Token';

const DEFAULT_TIMEOUT_MS = 10000;

// ============================================================================
// Errors
// ============================================================================

/** Thrown for any non-2xx response, with the backend envelope unpacked. */
export class ApiError extends Error {
  readonly status: number;
  readonly details?: unknown;
  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

// ============================================================================
// Token helpers (single source of truth for the storage keys)
// ============================================================================

function readStorage(key: string): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(key);
}

function clearSession(): void {
  if (typeof window === 'undefined') return;
  // Tokens live in httpOnly cookies now; still purge legacy localStorage tokens
  // from any browser that stored them before E0-5, plus the profile.
  localStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
  localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Read the double-submit CSRF token the backend set as a JS-readable cookie. */
export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]+)`));
  return m ? decodeURIComponent(m[1]) : null;
}

/** Headers a state-changing request must carry: the CSRF token, when present. */
function csrfHeaders(method: string): Record<string, string> {
  if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return {};
  const token = getCsrfToken();
  return token ? { [CSRF_HEADER]: token } : {};
}

/** Mint the csrf_token cookie if we don't have one yet (a mutation fired before
 *  any API GET would otherwise 403). A cheap authenticated GET sets it. */
async function ensureCsrfToken(): Promise<void> {
  if (getCsrfToken()) return;
  try {
    await fetch(`${API_URL}/api/auth/validate`, {
      method: 'GET',
      credentials: 'include',
    });
  } catch {
    /* offline / network — the caller's own request will surface the error */
  }
}

// ============================================================================
// Authorization-aware response cache (E0-6)
// ============================================================================
//
// Keying the cache on user id alone was not enough. The backend scopes every
// response by (tenant, role, accessible stores) — so two requests from the same
// user id can legitimately return different data, and the cache would serve the
// first answer for the second question. A role switch, a tenant switch, or a
// permission grant/revoke all keep `user.id` constant while changing what that
// user is allowed to see. The key below covers the whole authorization scope,
// so a stale privileged response can never be read back under a narrower one.

interface CachedIdentity {
  id?: number;
  tenant_id?: number;
  role?: string;
  accessible_stores?: number[];
  accessible_regions?: string[];
  permissions?: { accessible_stores?: number[]; accessible_regions?: string[] };
}

const ANON_IDENTITY = 'anon';

/** Fingerprint of everything the backend uses to scope a response. */
function identityFingerprint(): string {
  const raw = readStorage(USER_KEY);
  if (!raw) return ANON_IDENTITY;
  try {
    const u = JSON.parse(raw) as CachedIdentity;
    if (u.id == null) return ANON_IDENTITY;

    const stores = [...(u.accessible_stores ?? u.permissions?.accessible_stores ?? [])]
      .sort((a, b) => a - b)
      .join('.');
    const regions = [...(u.accessible_regions ?? u.permissions?.accessible_regions ?? [])]
      .sort()
      .join('.');

    return [u.id, u.tenant_id ?? '-', u.role ?? '-', stores, regions].join('|');
  } catch {
    return ANON_IDENTITY;
  }
}

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

const cache = new Map<string, CacheEntry<unknown>>();

/** Last identity we served from cache, so a change can flush it. */
let lastIdentity: string | null = null;

/**
 * Current identity, flushing the cache if it changed since the last request.
 *
 * Keying alone already prevents a cross-scope read. This flush is the second
 * layer: it bounds memory across role switches, and it means a *revert* to a
 * previous role starts cold rather than replaying entries cached before the
 * permission change that prompted the switch.
 */
function currentIdentity(): string {
  const identity = identityFingerprint();
  if (lastIdentity !== null && lastIdentity !== identity) cache.clear();
  lastIdentity = identity;
  return identity;
}

function cacheKey(identity: string, url: string): string {
  return `${identity}::${url}`;
}

/** Clear the whole cache, or only entries whose key contains `pattern`. */
export function clearApiCache(pattern?: string): void {
  if (!pattern) {
    cache.clear();
    lastIdentity = null;
    return;
  }
  for (const key of cache.keys()) {
    if (key.includes(pattern)) cache.delete(key);
  }
}

// ============================================================================
// Token refresh (single-flight so concurrent 401s trigger one refresh)
// ============================================================================

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      // The refresh token rides along as an httpOnly cookie — send NO body
      // (RefreshRequest requires a token, so `{}` would 422; the endpoint falls
      // back to the cookie when the body is absent). /api/auth/refresh is
      // CSRF-exempt. The rotated access/refresh cookies come back as Set-Cookie.
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) return false;
      const data = await res.json();
      // Only the profile is persisted (for cache scoping) — never the tokens.
      if (typeof window !== 'undefined' && data.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      }
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

// ============================================================================
// Core request
// ============================================================================

function buildUrl(endpoint: string, params?: Record<string, unknown>): string {
  const base = endpoint.startsWith('http') ? endpoint : `${API_URL}${endpoint}`;
  if (!params || Object.keys(params).length === 0) return base;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.append(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${base}?${qs}` : base;
}

async function parseError(res: Response): Promise<ApiError> {
  let message = `HTTP ${res.status}`;
  let details: unknown;
  try {
    const body = await res.json();
    // backend envelope: { error, status_code, message, details } — or FastAPI { detail }
    message = body?.message || body?.detail || message;
    details = body?.details;
  } catch {
    /* non-JSON body — keep the status-code message */
  }
  return new ApiError(message, res.status, details);
}

/**
 * Authenticated fetch returning the raw Response. Auth is the httpOnly cookie
 * (credentials:'include'); state-changing requests carry the CSRF double-submit
 * header. On 401 it refreshes once and retries; on a CSRF 403 it mints the token
 * and retries once. Use for streaming/blob responses; JSON callers use the typed
 * helpers below. Does not cache.
 */
export async function authFetch(
  endpoint: string,
  options: RequestInit = {},
): Promise<Response> {
  const url = buildUrl(endpoint);
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    await ensureCsrfToken();
  }
  const send = (): Promise<Response> =>
    fetch(url, {
      ...options,
      credentials: 'include',
      headers: {
        ...options.headers,
        ...csrfHeaders(method),
      },
    });

  let res = await send();
  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await send();
    } else if (typeof window !== 'undefined') {
      clearSession();
      clearApiCache();
      window.location.href = '/login';
    }
  } else if (res.status === 403 && (await isCsrfFailure(res))) {
    await ensureCsrfToken();
    res = await send();
  }
  return res;
}

/** Whether a 403 is a CSRF-token failure (so we retry) vs a real authz denial. */
async function isCsrfFailure(res: Response): Promise<boolean> {
  try {
    const body = await res.clone().json();
    const msg = String(body?.message || body?.detail || '').toLowerCase();
    return msg.includes('csrf');
  } catch {
    return false;
  }
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  params?: Record<string, unknown>;
  body?: unknown;
  /** Cache successful GETs for this many ms (user-scoped). */
  ttl?: number;
  timeoutMs?: number;
}

/** Typed JSON request with auth, refresh-retry, error envelope, and caching. */
export async function apiRequest<T>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<T> {
  const { params, body, ttl, timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = options;
  const method = (rest.method || 'GET').toUpperCase();
  const url = buildUrl(endpoint, params);

  const canCache = method === 'GET' && ttl != null && ttl > 0;
  const key = cacheKey(currentIdentity(), url);
  if (canCache) {
    const hit = cache.get(key) as CacheEntry<T> | undefined;
    if (hit && hit.expiresAt > Date.now()) return hit.data;
    if (hit) cache.delete(key);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const send = (): Promise<Response> =>
    fetch(url, {
      ...rest,
      method,
      credentials: 'include',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...rest.headers,
        ...csrfHeaders(method),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });

  try {
    if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
      await ensureCsrfToken();
    }
    let res = await send();
    if (res.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        res = await send();
      } else if (typeof window !== 'undefined') {
        clearSession();
        clearApiCache();
        window.location.href = '/login';
      }
    } else if (res.status === 403 && (await isCsrfFailure(res))) {
      await ensureCsrfToken();
      res = await send();
    }

    if (!res.ok) throw await parseError(res);

    const data = (await res.json()) as T;
    // A 401-refresh mid-flight can hand back a different role/tenant. Only cache
    // if the scope that keyed this request is still the live one — otherwise the
    // entry belongs to an identity that no longer holds.
    if (canCache && identityFingerprint() === key.slice(0, key.indexOf('::'))) {
      cache.set(key, { data, expiresAt: Date.now() + ttl! });
      if (cache.size > 200) {
        const now = Date.now();
        for (const [k, v] of cache) if (v.expiresAt <= now) cache.delete(k);
      }
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

export const apiGet = <T>(endpoint: string, options: RequestOptions = {}): Promise<T> =>
  apiRequest<T>(endpoint, { ...options, method: 'GET' });

export const apiPost = <T>(endpoint: string, body?: unknown, options: RequestOptions = {}): Promise<T> =>
  apiRequest<T>(endpoint, { ...options, method: 'POST', body });

export const apiPut = <T>(endpoint: string, body?: unknown, options: RequestOptions = {}): Promise<T> =>
  apiRequest<T>(endpoint, { ...options, method: 'PUT', body });

export const apiDelete = <T>(endpoint: string, options: RequestOptions = {}): Promise<T> =>
  apiRequest<T>(endpoint, { ...options, method: 'DELETE' });
