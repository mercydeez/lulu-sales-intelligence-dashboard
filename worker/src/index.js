// Diagnostics worker entrypoint (A3). BullMQ on the EXISTING Redis: a repeatable
// "scan" job fires on a schedule; the Worker runs the deterministic rules and
// upserts findings. Reuses the same Redis the app already runs — no new infra.
import { Queue, Worker } from "bullmq";
import IORedis from "ioredis";

import { runScan } from "./scan.js";
import { runMeasure } from "./measure.js";
import { pool } from "./db.js";

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

const worker = new Worker(
  QUEUE_NAME,
  async (job) => {
    console.log(`[worker] processing ${job.name}`);
    return job.name === "measure" ? runMeasure() : runScan();
  },
  { connection, concurrency: 1 }
);

worker.on("completed", (job, res) => console.log(`[worker] ${job.name} done:`, res));
worker.on("failed", (job, err) => console.error(`[worker] ${job?.name} failed:`, err?.message));

async function bootstrap() {
  // Run one scan immediately so the dashboard has findings on first boot.
  try {
    await runScan();
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
