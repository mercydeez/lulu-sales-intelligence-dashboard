/**
 * Webhook delivery jobs.
 *
 * Two job types on the `webhook` queue:
 *  - `dispatch` {tenant_id, event, data}: expand the tenant's subscribed
 *    endpoints and enqueue one `deliver` job per endpoint. This gives each
 *    endpoint its OWN retry/backoff — a slow receiver never re-fires a
 *    successful one.
 *  - `deliver` {webhookId, url, secret, body}: a single signed POST. Throws on
 *    failure so BullMQ retries it with exponential backoff; updates delivery
 *    status in `tenant_webhooks` either way.
 *
 * Signing matches backend/app/services/webhook_service.py exactly:
 * HMAC-SHA256(secret, body) hex, header `X-Webhook-Signature: sha256=<hex>`,
 * over a body of `{event, tenant_id, data, sent_at}`.
 */
import { Job } from "bullmq";
import * as crypto from "crypto";
import { pool } from "../db";
import { enqueue, Q_WEBHOOK } from "../queues";
import { DELIVERY_TIMEOUT_MS } from "../config";

const SIGNATURE_HEADER = "X-Webhook-Signature";

function sign(secret: string, body: string): string {
  return crypto.createHmac("sha256", secret).update(body, "utf8").digest("hex");
}

function subscribed(events: string[] | null, event: string): boolean {
  const e = events && events.length ? events : ["*"];
  return e.includes("*") || e.includes(event);
}

export async function handleDispatch(job: Job): Promise<{ fanned_out: number }> {
  const { tenant_id, event, data } = job.data as {
    tenant_id: number;
    event: string;
    data: unknown;
  };

  const { rows } = await pool.query(
    `SELECT id, url, secret, events FROM tenant_webhooks
     WHERE tenant_id = $1 AND active = TRUE`,
    [tenant_id],
  );
  const targets = rows.filter((r) => subscribed(r.events, event));
  if (targets.length === 0) return { fanned_out: 0 };

  const body = JSON.stringify({
    event,
    tenant_id,
    data,
    sent_at: new Date().toISOString(),
  });

  for (const t of targets) {
    await enqueue(Q_WEBHOOK, "deliver", {
      webhookId: t.id,
      url: t.url,
      secret: t.secret,
      body,
    });
  }
  return { fanned_out: targets.length };
}

export async function handleDeliver(job: Job): Promise<{ status: number }> {
  const { webhookId, url, secret, body } = job.data as {
    webhookId: number;
    url: string;
    secret: string;
    body: string;
  };

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    [SIGNATURE_HEADER]: `sha256=${sign(secret, body)}`,
    "User-Agent": "Foresia-Webhooks/1.0",
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DELIVERY_TIMEOUT_MS);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers,
      body,
      signal: controller.signal,
    });
    await pool.query(
      `UPDATE tenant_webhooks
       SET last_delivery_at = NOW(), last_status = $1,
           failure_count = CASE WHEN $1 >= 400 THEN failure_count + 1 ELSE 0 END
       WHERE id = $2`,
      [resp.status, webhookId],
    );
    if (resp.status >= 400) {
      throw new Error(`HTTP ${resp.status} from ${url}`);
    }
    return { status: resp.status };
  } catch (err) {
    await pool.query(
      `UPDATE tenant_webhooks
       SET last_delivery_at = NOW(), failure_count = failure_count + 1
       WHERE id = $1`,
      [webhookId],
    );
    throw err; // surface to BullMQ → retry with backoff
  } finally {
    clearTimeout(timer);
  }
}

export async function processWebhookJob(job: Job): Promise<unknown> {
  if (job.name === "dispatch") return handleDispatch(job);
  if (job.name === "deliver") return handleDeliver(job);
  throw new Error(`Unknown webhook job: ${job.name}`);
}
