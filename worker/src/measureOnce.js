// Run a single measure pass and exit — for manual runs, CI smoke, and tests.
//   docker compose run --rm worker npm run measure:once
import { runMeasure } from "./measure.js";
import { pool } from "./db.js";

runMeasure()
  .then((res) => {
    console.log("[measure:once] result:", res);
    return pool.end();
  })
  .then(() => process.exit(0))
  .catch(async (e) => {
    console.error("[measure:once] error:", e);
    await pool.end().catch(() => {});
    process.exit(1);
  });
