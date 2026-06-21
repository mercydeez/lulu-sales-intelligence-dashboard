/**
 * Worker configuration — read from the environment (set by docker-compose).
 *
 * REDIS_URL must point at the SAME Redis the FastAPI producer uses, and BullMQ's
 * default key prefix ("bull") must match on both sides so jobs added by the
 * Python `bullmq` client are picked up here.
 *
 * DATABASE_URL is a plain libpq URL (postgres://...), distinct from the backend's
 * SQLAlchemy "+asyncpg" URL. We normalize either form just in case.
 */

export const REDIS_URL = process.env.REDIS_URL || "redis://redis:6379";

export const DATABASE_URL = (
  process.env.DATABASE_URL || "postgres://salesuser:salespass@postgres:5432/salesdb"
).replace("postgresql+asyncpg://", "postgresql://");

export const HEALTH_PORT = parseInt(process.env.WORKER_HEALTH_PORT || "9100", 10);

// How many jobs a single worker processes concurrently.
export const CONCURRENCY = parseInt(process.env.WORKER_CONCURRENCY || "8", 10);

// Webhook delivery tuning.
export const DELIVERY_TIMEOUT_MS = parseInt(
  process.env.WEBHOOK_TIMEOUT_MS || "5000",
  10,
);

// Risk scans: the worker triggers the Python scan via an internal endpoint on a
// schedule (the heavy compute stays in Python; BullMQ owns durable scheduling).
export const BACKEND_URL = process.env.BACKEND_URL || "http://backend:8000";
export const INTERNAL_API_TOKEN =
  process.env.INTERNAL_API_TOKEN || "foresia-internal-dev-token";
export const RISK_SCAN_EVERY_MS = parseInt(
  process.env.RISK_SCAN_EVERY_MS || "600000", // 10 minutes
  10,
);
