/**
 * Foresia BullMQ worker — entrypoint.
 *
 * Starts a Worker per queue, a tiny HTTP /health endpoint (for the compose
 * healthcheck), and wires graceful shutdown. Currently processes the `webhook`
 * queue; the `risk-scan` queue is added in Phase 3.
 */
import * as http from "http";
import { Worker } from "bullmq";
import { connection } from "./redis";
import { Q_WEBHOOK, Q_RISK_SCAN, getQueue, closeQueues } from "./queues";
import { processWebhookJob } from "./jobs/webhook";
import { processRiskScanJob } from "./jobs/riskScan";
import { CONCURRENCY, HEALTH_PORT, RISK_SCAN_EVERY_MS } from "./config";

const workers: Worker[] = [];

function startWorker(name: string, processor: (job: any) => Promise<unknown>): Worker {
  const w = new Worker(name, processor, { connection, concurrency: CONCURRENCY });
  w.on("completed", (job) =>
    console.log(`[${name}] completed job ${job.id} (${job.name})`),
  );
  w.on("failed", (job, err) =>
    console.error(
      `[${name}] failed job ${job?.id} (${job?.name}) attempt ${job?.attemptsMade}: ${err.message}`,
    ),
  );
  w.on("error", (err) => console.error(`[${name}] worker error:`, err.message));
  workers.push(w);
  console.log(`[worker] listening on queue "${name}" (concurrency=${CONCURRENCY})`);
  return w;
}

// ── Queues ──────────────────────────────────────────────────────────────────
startWorker(Q_WEBHOOK, processWebhookJob);
startWorker(Q_RISK_SCAN, processRiskScanJob);

// Schedule the recurring risk scan + one shortly after boot (delayed so the
// backend is up). The repeatable jobId is stable so we don't stack duplicates.
(async () => {
  try {
    const q = getQueue(Q_RISK_SCAN);
    await q.add("scan-all", {}, {
      repeat: { every: RISK_SCAN_EVERY_MS },
      jobId: "risk-scan-cron",
      removeOnComplete: 50,
      removeOnFail: 50,
    });
    await q.add("scan-all", {}, { delay: 25_000, removeOnComplete: 50, removeOnFail: 50 });
    console.log(`[worker] risk scan scheduled every ${RISK_SCAN_EVERY_MS}ms`);
  } catch (err) {
    console.error("[worker] failed to schedule risk scan:", (err as Error).message);
  }
})();

// ── Health server ─────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  if (req.url === "/health") {
    const healthy = workers.every((w) => w.isRunning());
    res.writeHead(healthy ? 200 : 503, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        status: healthy ? "healthy" : "unhealthy",
        queues: workers.map((w) => w.name),
        ts: new Date().toISOString(),
      }),
    );
    return;
  }
  res.writeHead(404);
  res.end();
});
server.listen(HEALTH_PORT, () =>
  console.log(`[worker] health server on :${HEALTH_PORT}`),
);

// ── Graceful shutdown ─────────────────────────────────────────────────────────
async function shutdown(signal: string): Promise<void> {
  console.log(`[worker] ${signal} received, shutting down...`);
  server.close();
  await Promise.all(workers.map((w) => w.close()));
  await closeQueues();
  await connection.quit();
  process.exit(0);
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));

console.log("[worker] Foresia worker started");
