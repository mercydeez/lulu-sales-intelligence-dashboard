// Run a single diagnostics scan and exit — for manual runs, CI smoke, and tests.
//   docker compose run --rm worker npm run scan:once
import { runScan } from "./scan.js";
import { pool } from "./db.js";

runScan()
  .then((res) => {
    console.log("[scan:once] result:", res);
    return pool.end();
  })
  .then(() => process.exit(0))
  .catch(async (e) => {
    console.error("[scan:once] error:", e);
    await pool.end().catch(() => {});
    process.exit(1);
  });
