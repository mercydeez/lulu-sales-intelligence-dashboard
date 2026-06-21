/**
 * Shared Redis connection for BullMQ. `maxRetriesPerRequest: null` is required
 * by BullMQ workers (they issue blocking commands).
 */
import IORedis from "ioredis";
import { REDIS_URL } from "./config";

export const connection = new IORedis(REDIS_URL, {
  maxRetriesPerRequest: null,
  enableReadyCheck: true,
});

connection.on("error", (err) => {
  // ioredis reconnects automatically; log so failures are visible.
  console.error("[redis] connection error:", err.message);
});
