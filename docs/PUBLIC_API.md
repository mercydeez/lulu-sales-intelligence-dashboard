# Public API & Embeddable AI (B4/B5)

The platform exposes a per-tenant public REST API so customers can pull their
own intelligence — and embed the AI assistant — in their own apps. **The API
key *is* the tenant scope:** a key can only ever read its own tenant's data.

## Authentication

Every public request is authenticated by a per-tenant API key, sent either way:

```
Authorization: Bearer lsk_<prefix>_<secret>
# or
X-API-Key: lsk_<prefix>_<secret>
```

Keys are minted by a tenant admin and only the SHA-256 hash is stored — the
plaintext is shown **once**, at creation.

### Managing keys (authenticated dashboard session, admin role)

```
POST   /api/api-keys           {"name": "Reporting bot", "scopes": ["read"]}  -> { api_key: "lsk_...", ... }
GET    /api/api-keys           -> { keys: [ { key_prefix, scopes, last_used_at, request_count, revoked } ] }
DELETE /api/api-keys/{id}      -> { success: true, revoked: true }
```

`scopes` is one or more of `read`, `write`, `*`. The plaintext `api_key` in the
`POST` response is never retrievable again.

## Endpoints

| Method | Path                                        | Scope  | Returns |
|--------|---------------------------------------------|--------|---------|
| GET    | `/api/public/v1/kpis`                       | read   | Tenant KPIs (sales/revenue today/week/month, trends) |
| GET    | `/api/public/v1/forecast/projection?horizon=14` | read | Forward revenue projection (engine × avg price) |
| GET    | `/api/public/v1/inventory/reorder-suggestions?lead_time_days=7` | read | Forecast-driven reorder list |
| POST   | `/api/public/v1/ai/ask`                     | read   | Embeddable, tenant-scoped AI answer |

### Example: ask the AI assistant

```bash
curl -s https://your-host/api/public/v1/ai/ask \
  -H "Authorization: Bearer lsk_ab12cd34_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"question": "what is the sales forecast for next two weeks?", "horizon": 14}'
```

```json
{
  "question": "what is the sales forecast for next two weeks?",
  "answer": "📈 **14-Day Forecast** ... Projected sales: 12,480 units ...",
  "tenant_id": 2,
  "intents": ["prediction"]
}
```

The AI layer tries a local **Ollama** model first, then OpenAI if a key is
configured, and always falls back to a deterministic, data-grounded rule-based
answer — so it works with **zero paid keys**.

## Isolation guarantees

- The key resolves to exactly one tenant; every query is filtered by that
  `tenant_id` (app-layer scoping) and, under the production hardening, Postgres
  Row-Level Security (`app.tenant_id` GUC + `FORCE ROW LEVEL SECURITY` on a
  non-owner role) backs it up.
- Revoked or non-`active`-tenant keys are rejected with `401`.
- Missing/insufficient scope is rejected with `403`.

## Webhooks (outbound, signed)

A tenant admin registers HTTPS endpoints + the events they care about; the
platform POSTs a signed JSON payload when those events fire.

```
POST   /api/webhooks        {"url": "https://you/hook", "events": ["*"], "description": "ops"}
GET    /api/webhooks        -> { webhooks: [ { url, events, active, last_status, failure_count } ] }
DELETE /api/webhooks/{id}
POST   /api/webhooks/test   -> sends a signed `webhook.test` event to your endpoints
```

Each delivery carries `X-Lulu-Signature: sha256=<hex>`, an HMAC-SHA256 of the
exact request body using the endpoint's secret (returned once at creation).
Verify it on your side:

```python
import hmac, hashlib
expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, signature.split("=", 1)[1])
```

Payload shape: `{ "event", "tenant_id", "data", "sent_at" }`. Delivery is
best-effort and fire-and-forget, so a slow receiver never blocks the platform.

**Event types** (subscribe to specific ones or `*`):

| Event | Fires when |
|-------|-----------|
| `webhook.test` | You hit `POST /api/webhooks/test` |
| `purchase_order.created` | A draft PO is generated from the forecast |
| `purchase_order.approved` | A PO is approved (manually or auto-approved by rule) |
| `purchase_order.sent` | A PO is marked sent to the supplier |
| `purchase_order.received` | A PO is fully received |
| `goods.received` | A goods receipt is recorded (partial or full) |
| `invoice.match_exception` | A supplier invoice fails the 3-way match |

## Still to build (B4 remainder)

An interactive **developer portal** (live "try it" docs) and wiring
`dispatch_event` into specific domain events (alerts / reorder) — see
`implementation.md`.
