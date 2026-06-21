/**
 * Postgres pool (libpq via node-postgres). The worker reads webhook endpoints
 * and (Phase 3) writes risk findings. It connects as the same app DB user.
 */
import { Pool } from "pg";
import { DATABASE_URL } from "./config";

export const pool = new Pool({
  connectionString: DATABASE_URL,
  max: 5,
  idleTimeoutMillis: 30_000,
});

pool.on("error", (err) => {
  console.error("[db] pool error:", err.message);
});
