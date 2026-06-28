# Retail IQ — Manual Checks Required Before Pilot

> The CI gate matrix (Phase 13) automates most verification. These items still
> require a **human** before a real pilot deployment — they are environment-,
> judgment-, or credential-bound and cannot be asserted in CI.

## Secrets & configuration

- [ ] Generate fresh `JWT_SECRET_KEY` and `SECRET_KEY` (≥32 chars), unique per env.
- [ ] Set strong `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `WORKER_DB_PASSWORD`
      (no `salespass`, no defaults). Confirm `validate_security()` boots clean in
      `ENVIRONMENT=production`.
- [ ] Set `CORS_ORIGINS` to the real frontend origin(s) — never `*`.
- [ ] Confirm `DEMO_MODE=false` for a real-data pilot (and `LIVE_GENERATOR_ENABLED`
      stays off without demo mode).
- [ ] Decide `ENABLE_EXTERNAL_AI` (default off). If on, provision + scope the
      `OPENAI_API_KEY` and confirm the data-egress decision is signed off.

## Data & migrations

- [ ] Take a baseline backup and **test a restore** end-to-end (`RESTORE_FROM_BACKUP.md`).
- [ ] Confirm migrations applied cleanly against the real DB (no pending).
- [ ] If loading real tenant data, verify units-vs-AED convention and `unit_price_aed`.

## Security review (human judgment)

- [ ] Run `/security-review` on the release diff; triage findings.
- [ ] Confirm RLS enforcement (`USE_RLS_ROLE`) with a cross-tenant probe in staging.
- [ ] Rotate/scope all API keys; set `expires_in_days` where appropriate.
- [ ] Confirm admin MFA policy (`REQUIRE_MFA_FOR_ADMINS`) matches the pilot's needs.

## Legal & trust

- [ ] **Legal review** of `docs/legal/PRIVACY.md` and `TERMS.md` before publishing.
- [ ] Confirm no marketing/UI copy claims compliance, POS capability, or scale not
      supported (see `KNOWN_LIMITATIONS.md`).
- [ ] Name the data-request contact in the Privacy Notice.

## Observability & on-call

- [ ] Wire the metrics endpoint to the real monitoring backend; set alert routes.
- [ ] Confirm logs carry `request_id` and **no secrets** in the target log sink.
- [ ] Establish on-call + escalation; rehearse one runbook (`docs/runbooks/`).
