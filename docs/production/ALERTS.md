# Alerts

Suggested alert thresholds for a pilot. Tune to observed baselines. Each links to a
runbook. Wire to your provider (Sentry, Grafana, Render alerts) or the built-in
`SECURITY_ALERT_*` / `NOTIFY_WEBHOOK_URL` hooks.

| Alert | Condition | Severity | Runbook |
|-------|-----------|----------|---------|
| Readiness failing | `/health/ready` 503 for > 2 min | critical | [DB_OUTAGE](../runbooks/DB_OUTAGE.md) / [REDIS_OUTAGE](../runbooks/REDIS_OUTAGE.md) |
| High error rate | 5xx ratio > 5% over 5 min | critical | [HIGH_ERROR_RATE](../runbooks/HIGH_ERROR_RATE.md) |
| High latency | p95 `http_request_duration_seconds` > 1.5s over 10 min | high | [HIGH_LATENCY](../runbooks/HIGH_LATENCY.md) |
| DB pool saturated | in-use connections ≈ pool max sustained | high | [DB_OUTAGE](../runbooks/DB_OUTAGE.md) |
| Redis down | `/health/deep` `redis: error` | high | [REDIS_OUTAGE](../runbooks/REDIS_OUTAGE.md) |
| Migrations pending | `/health/ready` `migrations: pending` after deploy | high | [FAILED_MIGRATION](../runbooks/FAILED_MIGRATION.md) |
| Auth-failure spike | `auth_failures` rate ≫ baseline | high | [SUSPECTED_DATA_LEAK](../runbooks/SUSPECTED_DATA_LEAK.md) |
| Rate-limit spike | `rate_limit_hits` surge from few IPs | medium | (investigate abuse) |
| Import failures | `import_failures` increasing | medium | [IMPORT_FAILURES](../runbooks/IMPORT_FAILURES.md) |
| Worker stalled | no new `findings` / scan heartbeat in N min | medium | [WORKER_FAILURES](../runbooks/WORKER_FAILURES.md) |
| AI provider degraded | `ai_fallbacks` rate high / provider errors | low | [AI_PROVIDER_OUTAGE](../runbooks/AI_PROVIDER_OUTAGE.md) |
| SSE degraded | SSE client drops / stream errors | low | [SSE_DEGRADED](../runbooks/SSE_DEGRADED.md) |
| Data leak suspected | cross-tenant access / unexpected export | critical | [SUSPECTED_DATA_LEAK](../runbooks/SUSPECTED_DATA_LEAK.md) |

**Paging:** critical → page on-call; high → notify within business hours; medium/low
→ ticket. Always confirm with `/health/deep` before acting.
