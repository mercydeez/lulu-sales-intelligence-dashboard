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
import { Q_WEBHOOK } from "./queues";
import { closeQueues } from "./queues";
import { processWebhookJob } from "./jobs/webhook";
import { CONCURRENCY, HEALTH_PORT } from "./config";

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
