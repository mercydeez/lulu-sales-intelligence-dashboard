// Provider-agnostic notification dispatcher (Track B). Sends new high/critical
// findings to a webhook if one is configured, otherwise just logs. Works with any
// Slack/Discord/Teams *incoming webhook* URL — no paid service, no SDK. Set
// NOTIFY_WEBHOOK_URL to enable; until then this is a no-op (logs only), so the
// stack runs with zero external dependencies. It ALSO writes an in-app notification
// (Phase 7) so high/critical findings surface in the product's bell, with or
// without a webhook.
import { query } from "./db.js";

const WEBHOOK_URL = process.env.NOTIFY_WEBHOOK_URL || "";
const MIN_SEVERITY = (process.env.NOTIFY_MIN_SEVERITY || "high").toLowerCase();

const RANK = { low: 1, medium: 2, high: 3, critical: 4 };

function shouldNotify(severity) {
  return (RANK[severity] || 0) >= (RANK[MIN_SEVERITY] || 3);
}

// Best-effort in-app notification (tenant-wide). Never throws — a notification
// failure must not break the scan loop.
async function recordInApp(tenantId, finding) {
  try {
    await query(
      `INSERT INTO notifications (tenant_id, user_id, type, title, body, severity, link, metadata)
       VALUES ($1, NULL, 'finding', $2, $3, $4, '/insights', $5)`,
      [
        tenantId,
        finding.title,
        finding.recommended_action
          ? `${finding.detail}\nRecommended: ${finding.recommended_action}`
          : finding.detail,
        finding.severity,
        JSON.stringify({ finding_id: finding.id ?? null }),
      ],
    );
  } catch (e) {
    console.error("[notify] in-app insert error:", e.message);
  }
}

export async function dispatch(tenantId, finding) {
  if (!shouldNotify(finding.severity)) return false;
  await recordInApp(tenantId, finding);
  const text =
    `:rotating_light: *[${finding.severity.toUpperCase()}]* ${finding.title}\n` +
    `${finding.detail}` +
    (finding.recommended_action ? `\n*Recommended:* ${finding.recommended_action}` : "");

  if (!WEBHOOK_URL) {
    console.log(`[notify] (no webhook configured) tenant ${tenantId}: ${finding.title}`);
    return false;
  }
  try {
    const res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) console.error(`[notify] webhook ${res.status}`);
    return res.ok;
  } catch (e) {
    console.error("[notify] webhook error:", e.message);
    return false;
  }
}
