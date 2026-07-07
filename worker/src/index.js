// Diagnostics worker entrypoint (A3). BullMQ on the EXISTING Redis: a repeatable
// "scan" job fires on a schedule; the Worker runs the deterministic rules and
// upserts findings. Reuses the same Redis the app already runs — no new infra.
//
// E0-2: the worker also emits a Redis HEARTBEAT (health:worker:diagnostics) on a
// fixed interval and around each scan/measure, so the backend's /health can tell
// whether the worker is alive and fresh. Heartbeat failures are non-fatal.
import { Queue, Worker } from "bullmq";
import IORedis from "ioredis";

import { runScan } from "./scan.js";
import { runMeasure } from "./measure.js";
import { pool } from "./db.js";
import { startHeartbeat, emitHeartbeat, newState } from "./heartbeat.js";

const QUEUE_NAME = "diagnostics";
const SCAN_EVERY_MS = Number(process.env.DIAGNOSTICS_INTERVAL_MS || 5 * 60 * 1000); // 5 min
// Outcome measurement of accepted findings. Slower cadence than scan — recovery
// plays out over days, not minutes.
const MEASURE_EVERY_MS = Number(process.env.MEASURE_INTERVAL_MS || 60 * 60 * 1000); // 1 hr

// BullMQ requires maxRetriesPerRequest=null on its connection.
const connection = new IORedis(process.env.REDIS_URL || "redis://redis:6379", {
  maxRetriesPerRequest: null,
});

const queue = new Queue(QUEUE_NAME, { connection });

// Shared heartbeat state — updated around each job so operators see last scan/
// measure status without querying Postgres.
const hbState = newState();
let heartbeat = null;

async function runScanTracked() {
  hbState.last_scan_started_at = new Date().toISOString();
  try {
    const res = await runScan();
    hbState.last_scan_finished_at = new Date().toISOString();
    hbState.last_scan_status = "ok";
    await emitHeartbeat(connection, hbState);
    return res;
  } catch (e) {
    hbState.last_scan_finished_at = new Date().toISOString();
    hbState.last_scan_status = "error";
    await emitHeartbeat(connection, hbState);
    throw e;
  }
}

async function runMeasureTracked() {
  hbState.last_measure_started_at = new Date().toISOString();
  try {
    const res = await runMeasure();
    hbState.last_measure_finished_at = new Date().toISOString();
    hbState.last_measure_status = "ok";
    await emitHeartbeat(connection, hbState);
    return res;
  } catch (e) {
    hbState.last_measure_finished_at = new Date().toISOString();
    hbState.last_measure_status = "error";
    await emitHeartbeat(connection, hbState);
    throw e;
  }
}

const worker = new Worker(
  QUEUE_NAME,
  async (job) => {
    console.log(`[worker] processing ${job.name}`);
    return job.name === "measure" ? runMeasureTracked() : runScanTracked();
  },
  { connection, concurrency: 1 }
);

worker.on("completed", (job, res) => console.log(`[worker] ${job.name} done:`, res));
worker.on("failed", (job, err) => console.error(`[worker] ${job?.name} failed:`, err?.message));

async function bootstrap() {
  // Start the heartbeat FIRST so /health sees a live worker immediately, even
  // before the first scan completes.
  heartbeat = startHeartbeat(connection, hbState);

  // Run one scan immediately so the dashboard has findings on first boot.
  try {
    await runScanTracked();
  } catch (e) {
    console.error("[worker] initial scan failed:", e.message);
  }
  // Schedule the recurring scan (idempotent: same jobId replaces the schedule).
  await queue.add(
    "scan",
    {},
    {
      repeat: { every: SCAN_EVERY_MS },
      jobId: "diagnostics-scan",
      removeOnComplete: 20,
      removeOnFail: 20,
    }
  );
  // Schedule the recurring outcome measurement of accepted findings.
  await queue.add(
    "measure",
    {},
    {
      repeat: { every: MEASURE_EVERY_MS },
      jobId: "diagnostics-measure",
      removeOnComplete: 20,
      removeOnFail: 20,
    }
  );
  console.log(
    `[worker] diagnostics worker up; scanning every ${SCAN_EVERY_MS / 1000}s, ` +
      `measuring outcomes every ${MEASURE_EVERY_MS / 1000}s`
  );
}

async function shutdown() {
  console.log("[worker] shutting down…");
  if (heartbeat) heartbeat.stop();
  await worker.close();
  await queue.close();
  await connection.quit();
  await pool.end();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

bootstrap().catch((e) => {
  console.error("[worker] bootstrap error:", e);
  process.exit(1);
});
