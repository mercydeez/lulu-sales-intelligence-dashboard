# Runbook: AI Provider Outage

Sage degrades gracefully by design: local-first (Ollama) → optional external
(OpenAI) → **deterministic rule-based fallback** that always works with no provider.

**Symptom:** `ai_fallbacks` rate high; Sage answers come from the rule-based path;
provider timeouts in logs.

## 1. Confirm
- `/health/deep` `mode.local_ai` / `mode.external_ai`.
- Logs for provider connection/timeout errors.

## 2. Impact
- **No outage of the app.** Sage still answers via the deterministic responder, and
  every answer carries its evidence + a confidence/disclosure block
  ([../ai/SAGE_SAFETY.md](../ai/SAGE_SAFETY.md)).
- Quality is lower (template answers) until the provider returns.

## 3. Mitigate
- **Local model down (Ollama):** restart the `ollama` service / re-pull the model.
- **External down (OpenAI):** it is optional and off by default in production
  (`ENABLE_EXTERNAL_AI`). No action needed unless you rely on it; the fallback covers it.
- To stop trying a flaky external provider: `ENABLE_EXTERNAL_AI=false`.

## 4. After
Confirm `ai_fallbacks` returns to baseline once the provider recovers. The SQL guard
and tenant scoping are unaffected by provider state — safety does not depend on the LLM.
