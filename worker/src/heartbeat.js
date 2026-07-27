// Worker heartbeat (E0-2). The long-running diagnostics worker periodically
// writes a small JSON document to Redis so the backend's /health can tell whether
// the worker is alive and fresh — independent of BullMQ queue keys. The backend
// (health_checks.check_worker_heartbeat) reads this same key and stale threshold.
//
// Design: emit on a fixed interval AND around each scan/measure so status is
// current between jobs. Heartbeat failures are logged, never fatal — a Redis blip
// must not crash the worker (matches the app's fail-open posture). The Redis
// client is INJECTED (no direct ioredis dependency here), so this module is
// unit-testable with a stub and no network.

export const HEARTBEAT_KEY = "health:worker:diagnostics";

export function heartbeatIntervalMs() {
  return Number(process.env.WORKER_HEARTBEAT_INTERVAL_MS || 30000);
}

export function staleSeconds() {
  return Number(process.env.WORKER_HEARTBEAT_STALE_SECONDS || 120);
}

// TTL >= 2x the emit interval AND >= the stale threshold, so a single missed beat
// never expires the key before it's legitimately considered stale.
export function ttlSeconds() {
  const twoIntervals = Math.ceil((heartbeatIntervalMs() * 2) / 1000);
  return Math.max(twoIntervals, staleSeconds());
}

export function newState() {
  return {
    last_scan_started_at: null,
    last_scan_finished_at: null,
    last_scan_status: null,
    last_measure_started_at: null,
    last_measure_finished_at: null,
    last_measure_status: null,
  };
}

// Pure: build the heartbeat document from the shared state (now/pid/version
// injectable for tests).
export function buildHeartbeatPayload(state, opts = {}) {
  const now = opts.now || new Date();
  return {
    service: "diagnostics-worker",
    status: opts.status || "ok",
    timestamp: now.toISOString(),
    pid: opts.pid != null ? opts.pid : process.pid,
    version: opts.version || process.env.WORKER_VERSION || "1.0.0",
    last_scan_started_at: state.last_scan_started_at,
    last_scan_finished_at: state.last_scan_finished_at,
    last_scan_status: state.last_scan_status,
    last_measure_started_at: state.last_measure_started_at,
    last_measure_finished_at: state.last_measure_finished_at,
    last_measure_status: state.last_measure_status,
  };
}

// Write the heartbeat with a TTL. `redis` is any ioredis-compatible client
// (real or a test stub exposing set(key, val, "EX", ttl)).
export async function writeHeartbeat(redis, payload, ttl = ttlSeconds()) {
  return redis.set(HEARTBEAT_KEY, JSON.stringify(payload), "EX", ttl);
}

// Best-effort emit: build + write; swallow + log errors so a Redis blip is
// non-fatal. Returns true on success, false otherwise.
export async function emitHeartbeat(redis, state, opts = {}) {
  try {
    await writeHeartbeat(redis, buildHeartbeatPayload(state, opts));
    return true;
  } catch (e) {
    console.error("[heartbeat] emit failed:", e?.message);
    return false;
  }
}

// Emit immediately, then every interval. Returns a handle with stop().
export function startHeartbeat(redis, state) {
  emitHeartbeat(redis, state);
  const timer = setInterval(() => emitHeartbeat(redis, state), heartbeatIntervalMs());
  if (timer.unref) timer.unref();
  return { stop: () => clearInterval(timer) };
}
