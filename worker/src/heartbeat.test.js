// Unit tests for the worker heartbeat (E0-2) — pure + mocked Redis, no network.
//   npm test   (node --test, built in, zero deps)
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  HEARTBEAT_KEY,
  buildHeartbeatPayload,
  writeHeartbeat,
  emitHeartbeat,
  ttlSeconds,
  newState,
} from "./heartbeat.js";

function mockRedis() {
  const calls = [];
  return {
    calls,
    set: async (...args) => {
      calls.push(args);
      return "OK";
    },
  };
}

test("buildHeartbeatPayload has the required shape", () => {
  const state = newState();
  state.last_scan_started_at = "2026-07-07T00:00:00.000Z";
  state.last_scan_finished_at = "2026-07-07T00:00:01.000Z";
  state.last_scan_status = "ok";
  const p = buildHeartbeatPayload(state, {
    now: new Date("2026-07-07T00:00:02.000Z"),
    pid: 4321,
    version: "9.9.9",
  });
  assert.equal(p.service, "diagnostics-worker");
  assert.equal(p.status, "ok");
  assert.equal(p.timestamp, "2026-07-07T00:00:02.000Z");
  assert.equal(p.pid, 4321);
  assert.equal(p.version, "9.9.9");
  assert.equal(p.last_scan_status, "ok");
  assert.equal(p.last_scan_finished_at, "2026-07-07T00:00:01.000Z");
  // measure fields present (null until a measure runs)
  assert.ok("last_measure_status" in p);
});

test("writeHeartbeat sets the canonical key with an EX TTL", async () => {
  const redis = mockRedis();
  await writeHeartbeat(redis, buildHeartbeatPayload(newState()), 200);
  assert.equal(redis.calls.length, 1);
  const [key, value, exFlag, ttl] = redis.calls[0];
  assert.equal(key, HEARTBEAT_KEY);
  assert.equal(exFlag, "EX");
  assert.equal(ttl, 200);
  const parsed = JSON.parse(value);
  assert.equal(parsed.service, "diagnostics-worker");
});

test("ttlSeconds is at least 2x the interval and at least the stale threshold", () => {
  const ttl = ttlSeconds();
  assert.ok(ttl >= Math.ceil((30000 * 2) / 1000)); // default interval 30s -> >= 60
  assert.ok(ttl >= 120); // default stale threshold
});

test("emitHeartbeat is best-effort: returns true on success, false on Redis error", async () => {
  const ok = await emitHeartbeat(mockRedis(), newState());
  assert.equal(ok, true);

  const brokenRedis = {
    set: async () => {
      throw new Error("redis down");
    },
  };
  const failed = await emitHeartbeat(brokenRedis, newState());
  assert.equal(failed, false); // swallowed, non-fatal
});
