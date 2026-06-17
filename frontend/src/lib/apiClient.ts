/**
 * Single frontend API client (Phase 2.7).
 *
 * One place for: base URL, bearer auth, 401 -> refresh -> retry, a user-aware
 * response cache (so one user never sees another's cached data — GAP M2), and
 * parsing of the backend's JSON error envelope into a typed ApiError (GAP M3).
 *
 * Auth endpoints (login/refresh/logout) stay in AuthContext; everything else
 * should go through here. `authFetch` is exposed for callers that need the raw
 * Response (e.g. streaming/blob); typed JSON callers use apiGet/apiPost/etc.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const ACCESS_TOKEN_KEY = 'lulu_access_token';
const REFRESH_TOKEN_KEY = 'lulu_refresh_token';
const USER_KEY = 'lulu_user';

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

export function getAccessToken(): string | null {
  return readStorage(ACCESS_TOKEN_KEY);
}

function setTokens(accessToken: string, refreshToken: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

function clearSession(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Stable id for the logged-in user (or 'anon') — used to scope the cache. */
function currentUserId(): string {
  const raw = readStorage(USER_KEY);
  if (!raw) return 'anon';
  try {
    const id = (JSON.parse(raw) as { id?: number }).id;
    return id != null ? String(id) : 'anon';
  } catch {
    return 'anon';
  }
}

// ============================================================================
// User-aware response cache
// ============================================================================

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

const cache = new Map<string, CacheEntry<unknown>>();

function cacheKey(userId: string, url: string): string {
  return `${userId}::${url}`;
}

/** Clear the whole cache, or only entries whose key contains `pattern`. */
export function clearApiCache(pattern?: string): void {
  if (!pattern) {
    cache.clear();
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
    const refreshToken = readStorage(REFRESH_TOKEN_KEY);
    if (!refreshToken) return false;
    try {
      const res = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
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
 * Authenticated fetch returning the raw Response. Adds the bearer token and,
 * on a 401, refreshes once and retries. Use for streaming/blob responses; for
 * JSON use the typed helpers below. Does not cache.
 */
export async function authFetch(
  endpoint: string,
  options: RequestInit = {},
): Promise<Response> {
  const url = buildUrl(endpoint);
  const send = (token: string | null): Promise<Response> =>
    fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });

  let res = await send(getAccessToken());
  if (res.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      res = await send(getAccessToken());
    } else if (typeof window !== 'undefined') {
      clearSession();
      clearApiCache();
      window.location.href = '/login';
    }
  }
  return res;
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
  const key = cacheKey(currentUserId(), url);
  if (canCache) {
    const hit = cache.get(key) as CacheEntry<T> | undefined;
    if (hit && hit.expiresAt > Date.now()) return hit.data;
    if (hit) cache.delete(key);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const send = (token: string | null): Promise<Response> =>
    fetch(url, {
      ...rest,
      method,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...rest.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });

  try {
    let res = await send(getAccessToken());
    if (res.status === 401) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        res = await send(getAccessToken());
      } else if (typeof window !== 'undefined') {
        clearSession();
        clearApiCache();
        window.location.href = '/login';
      }
    }

    if (!res.ok) throw await parseError(res);

    const data = (await res.json()) as T;
    if (canCache) {
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
