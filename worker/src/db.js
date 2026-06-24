// Postgres access for the diagnostics worker. Trusted code: it iterates tenants
// and scopes every query with an explicit `tenant_id = $1` (app-layer scoping).
// Connects as the least-privilege `worker_rw` role (migration 029) via
// WORKER_DATABASE_URL — SELECT on sales/items/stores + R/W on findings only, no
// access to users/credentials. Falls back to DATABASE_URL if unset.
import pg from "pg";

const { Pool } = pg;

// The Python app uses a SQLAlchemy URL (postgresql+asyncpg://). node-postgres wants
// a libpq URL (postgresql://) — strip the driver suffix if present.
function normalizeUrl(url) {
  if (!url) return url;
  return url.replace("postgresql+asyncpg://", "postgresql://");
}

export const pool = new Pool({
  connectionString: normalizeUrl(
    process.env.WORKER_DATABASE_URL ||
      process.env.DATABASE_URL ||
      "postgresql://salesuser:salespass@postgres:5432/salesdb"
  ),
  max: 4,
  idleTimeoutMillis: 30000,
});

export async function query(text, params) {
  const res = await pool.query(text, params);
  return res.rows;
}

export async function listTenantIds() {
  const rows = await query("SELECT DISTINCT tenant_id FROM stores ORDER BY tenant_id");
  return rows.map((r) => r.tenant_id);
}
