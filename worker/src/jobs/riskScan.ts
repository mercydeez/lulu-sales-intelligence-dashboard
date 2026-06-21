/**
 * Risk-scan job.
 *
 * The proactive detectors live in Python (they reuse the forecasting engine and
 * tenant-scoped SQL). This job is the durable SCHEDULER + trigger: it calls the
 * backend's internal all-tenant scan endpoint. BullMQ gives it retries/backoff
 * and a repeatable schedule, so a transient backend hiccup just reschedules.
 */
import { Job } from "bullmq";
import { BACKEND_URL, INTERNAL_API_TOKEN } from "../config";

export async function processRiskScanJob(_job: Job): Promise<unknown> {
  const resp = await fetch(`${BACKEND_URL}/api/intelligence/scan/internal`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Token": INTERNAL_API_TOKEN,
    },
  });
  if (!resp.ok) {
    throw new Error(`risk scan trigger failed: HTTP ${resp.status}`);
  }
  return (await resp.json().catch(() => ({}))) as unknown;
}
