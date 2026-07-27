# Retail IQ — AI Safety (Phase 11)

> How the Sage AI assistant is kept safe for a production/pilot tenant: data never
> leaves to a third party unless explicitly opted in, the public surface discloses
> no schema, every answer is grounded and labelled, and the AI cannot take an
> autonomous action.

## 1. External AI is off by default

`get_provider_chain()` (`backend/app/services/llm/__init__.py`) builds the LLM
provider order from feature flags, not from the mere presence of a key:

| Provider | Flag | Default | Effect when off |
|----------|------|:-------:|-----------------|
| Local (Ollama) | `ENABLE_LOCAL_AI` | `true` | skipped |
| External (OpenAI) | `ENABLE_EXTERNAL_AI` | **`false` everywhere** | skipped — tenant data never leaves to a 3rd-party LLM |

With both off, callers fall back to the **deterministic, data-grounded responder**
— so the assistant still works with zero paid keys and zero external egress.

`validate_security()` additionally rejects `ENABLE_EXTERNAL_AI=true` without a
configured `OPENAI_API_KEY` in production (fail-closed, no silent no-op).

## 2. The public API never returns raw SQL in production

`POST /v1/ai/ask` (`routes/public_api.py`) is an API-key, public surface. Raw
generated SQL is schema/info disclosure, so `_expose_sql()` returns it **only in
development** (`environment not in {production, prod, staging}`). In prod the
response carries the answer + an evidence block instead.

## 3. Every answer carries evidence + a data disclosure

`_ai_evidence()` attaches a non-sensitive provenance block to every AI response
(Sage, Sage v2 multipart, and the deterministic fallback):

```json
{
  "tenant_scope": 3,
  "rows_examined": 5,
  "confidence": "high | medium | low",
  "data_disclosure": "Sample/synthetic demo data — not real customer data"
}
```

- `tenant_scope` proves the answer was scoped to the caller's tenant.
- `confidence` is `high` only when grounded **and** rows were examined.
- `data_disclosure` flips on `DEMO_MODE` so a pilot viewer is never misled into
  treating synthetic demo data as real customer data.

## 4. The AI cannot take an autonomous action

The assistant is **read-only by construction**: Sage uses the NL→SQL guard
(`services/nl2sql.py`) which is SELECT-only, restricted to an allow-list of
curated tenant views, and tenant-scoped (see `test_nl2sql_guard.py`). There is no
endpoint by which the AI writes, mutates, or executes anything. Any operational
"action" derived from an answer (e.g. a reorder) is a **draft surfaced to a human**
in the dashboard, never executed by the model. This satisfies the
"human-approved" requirement by removing the autonomous path entirely.

## 5. Cross-tenant / injection / write-SQL prompts are rejected

Guard behaviour is covered by `tests/test_nl2sql_guard.py`; the Phase 11 gating,
SQL-hiding, and evidence/disclosure behaviour by `tests/test_ai_safety.py`.

## Config reference

| Env var | Default (dev / prod) | Purpose |
|---------|:--------------------:|---------|
| `ENABLE_EXTERNAL_AI` | `false` / `false` | allow 3rd-party LLM egress |
| `ENABLE_LOCAL_AI` | `true` / `true` | allow local Ollama |
| `DEMO_MODE` | `true` / `false` | drives the synthetic-data disclosure |
| `OPENAI_API_KEY` | unset | required if external AI is enabled |
