// Provider-agnostic notification dispatcher (Track B). Sends new high/critical
// findings to a webhook if one is configured, otherwise just logs. Works with any
// Slack/Discord/Teams *incoming webhook* URL — no paid service, no SDK. Set
// NOTIFY_WEBHOOK_URL to enable; until then this is a no-op (logs only), so the
// stack runs with zero external dependencies.
const WEBHOOK_URL = process.env.NOTIFY_WEBHOOK_URL || "";
const MIN_SEVERITY = (process.env.NOTIFY_MIN_SEVERITY || "high").toLowerCase();

const RANK = { low: 1, medium: 2, high: 3, critical: 4 };

function shouldNotify(severity) {
  return (RANK[severity] || 0) >= (RANK[MIN_SEVERITY] || 3);
}

export async function dispatch(tenantId, finding) {
  if (!shouldNotify(finding.severity)) return false;
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
