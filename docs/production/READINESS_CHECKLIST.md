# Retail IQ — Production Readiness Checklist

> Living checklist used as the GO/NO-GO input (Phase 14). Each item is checkable and maps to a phase. State at program start: nearly all **unchecked**. Update the boxes as phases land.

## Configuration & secrets (Phase 1)
- [ ] Production rejects default `JWT_SECRET_KEY` / `SECRET_KEY`
- [ ] Production rejects secrets `<32` chars
- [ ] Production rejects default DB password (`salespass`) and default infra passwords
- [ ] Production rejects wildcard CORS
- [ ] `ALLOW_DEMO_USERS=true` rejected in production
- [ ] API docs exposed only via explicit `EXPOSE_API_DOCS` protected mode
- [ ] `LIVE_GENERATOR_ENABLED` rejected without `DEMO_MODE`
- [ ] `RUN_MIGRATIONS_ON_STARTUP` / `RUN_SEED_ON_STARTUP` rejected in production
- [ ] External AI rejected without explicit opt-in
- [ ] `.env.example` and `.env.production.example` present, no real secrets

## Runtime topology (Phase 2)
- [ ] Production API does **not** run migrations from lifespan
- [ ] Production API does **not** run seed from lifespan
- [ ] Production API does **not** start the synthetic generator
- [ ] `backend/app/commands/*` exist and are entrypoint-safe
- [ ] Prod compose has `migrate` one-shot, `worker`, demo-only `generator`
- [ ] Redis requires a password in prod compose
- [ ] No default production credentials anywhere in compose

## Health (Phase 3)
- [ ] `/health/live` independent of DB/Redis
- [ ] `/health/ready` checks DB + Redis + migrations + config
- [ ] `/health/deep` reports subsystems without leaking secrets
- [ ] `/health` remains backward-compatible
- [ ] Compose + `render.yaml` use `/health/ready`

## Backup & recovery (Phase 4)
- [ ] `backup-postgres.sh`, `restore-postgres.sh`, `verify-backup.sh` parse (`bash -n`)
- [ ] Restore refuses accidental prod restore without explicit confirm
- [ ] RPO/RTO documented for pilot
- [ ] Rollback + DR runbooks exist

## Auth lifecycle (Phase 5)
- [ ] Reset tokens hashed, single-use, expiring; reset revokes sessions
- [ ] Verify tokens single-use
- [ ] Invite tokens single-use with expiry + tenant + role
- [ ] Session list + revoke (one/all)
- [ ] `REQUIRE_MFA_FOR_ADMINS` enforced when set
- [ ] No account enumeration

## Tenant isolation (Phase 6)
- [ ] `get_active_source`/`set_active` tenant-scoped
- [ ] Per-tenant active-source unique index (migration 037)
- [ ] Tenant A cannot list/test/activate/delete Tenant B sources (tests pass)
- [ ] Connector testing gated by `ENABLE_DATA_SOURCE_CONNECTORS` in prod
- [ ] Credentials never serialized/logged

## Observability (Phase 9)
- [ ] JSON logs carry `request_id` (+ tenant/user where safe, no secrets)
- [ ] Metrics endpoint/exporter present
- [ ] Incident runbooks present
- [ ] Metrics/logs leak no secrets (tested)

## Frontend QA (Phase 10)
- [ ] `tsc --noEmit` passes
- [ ] `npm run build` passes
- [ ] Component + Playwright smoke configured and passing
- [ ] Every major page handles loading/empty/error/forbidden states
- [ ] Demo/sample data labelled in UI

## AI safety (Phase 11)
- [x] External AI off by default in production (`ENABLE_EXTERNAL_AI=false`)
- [x] Public API returns no raw SQL in production (`_expose_sql()`)
- [x] AI answers carry an evidence block + demo-data disclosure (`_ai_evidence()`)
- [x] AI actions require human approval (assistant is read-only by construction)
- [x] Cross-tenant / injection / write-SQL prompts rejected (`test_nl2sql_guard.py`, `test_ai_safety.py`)

## Trust & legal (Phase 12)
- [ ] Tenant export scoped; cross-tenant download blocked
- [ ] Delete-on-request workflow + audit
- [ ] Legal drafts present, marked "draft — legal review required"
- [ ] No false compliance / POS / scale claims

## CI/CD (Phase 13)
- [ ] CI runs full backend pytest + config/security/isolation/AI suites
- [ ] CI runs FE typecheck + build (+ tests/Playwright if configured)
- [ ] CI validates both compose files
- [ ] CI runs fresh-DB + existing-DB migration
- [ ] CI runs backup/restore syntax + dependency/image scan

## Final gate (Phase 14)
- [ ] Full gate battery run with recorded output
- [ ] `FINAL_RELEASE_REPORT.md`, `GO_NO_GO_DECISION.md`, `KNOWN_LIMITATIONS.md`, `MANUAL_CHECKS_REQUIRED.md`, `POST_LAUNCH_MONITORING.md` written
- [ ] Honest GO / CONDITIONAL-GO / NO-GO recorded with blockers
- [ ] README remains honest about synthetic data
