# Retail IQ — Production Risk Register

> Top risks ranked by **severity** (Critical → High → Medium → Low), each with likelihood, impact, current mitigation, and the phase that closes it. Severity reflects state **at the start** of the hardening program; the "Status" column updates as phases land.

Legend — Sev: 🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low. Status: OPEN / IN-PROGRESS / CLOSED.

| # | Risk | Sev | Likelihood | Impact | Current mitigation | Closes in | Status |
|---|------|:---:|------------|--------|--------------------|:---------:|:------:|
| 1 | Cross-tenant active data-source flip (`get_active_source`/`set_active` unscoped) | 🔴 | High | Tenant A alters Tenant B config | None | P6 | OPEN |
| 2 | Reset/verify tokens replayable (no `used_at` write) | 🔴 | Medium | Account takeover within token window | JWT expiry only | P5 | OPEN |
| 3 | Migrations run from every API replica | 🔴 | High (multi-replica) | Concurrent/locked migrations, partial schema | Single-replica only today | P2 | OPEN |
| 4 | Synthetic generator runs in production API | 🔴 | High | Fake data written into a "real" tenant | None | P1/P2 | OPEN |
| 5 | Seed runs from every API replica | 🟠 | High (multi-replica) | Duplicate/competing seeds | Idempotent seed | P2 | OPEN |
| 6 | Production accepts unsafe config (no fail-closed flags) | 🟠 | Medium | Demo users / docs / wildcard CORS in prod | Partial (`validate_security`) | P1 | OPEN |
| 7 | Redis unauthenticated in prod compose | 🟠 | Medium | Token blacklist + cache tampering | Internal network only | P2 | OPEN |
| 8 | No backup/restore → unrecoverable data loss | 🟢 | Low (residual) | Total data loss on disk/DB failure | **Automated nightly backups (verified) + CI-enforced restore drill (E0-1)**; residual = configure offsite `BACKUP_S3_URL`/snapshots + quarterly live drill per deploy | P4 | MITIGATED |
| 9 | No readiness probe → traffic before deps ready | 🟠 | High | 5xx storms on deploy/restart | Basic `/health` | P3 | OPEN |
| 10 | External AI could exfiltrate tenant data unflagged | 🟠 | Low–Med | Tenant data to 3rd-party LLM | Local-first + fallback | P11 | OPEN |
| 11 | Public API could surface raw SQL | 🟠 | Low | Schema disclosure | SELECT-only guard | P11 | OPEN |
| 12 | No single-use invite tokens (temp-password invites) | 🟡 | Medium | Invite reuse / weaker onboarding | Temp password expiry | P5 | OPEN |
| 13 | No session list/revoke | 🟡 | Medium | Can't kill a stolen session | Global logout + blacklist | P5 | OPEN |
| 14 | Admin MFA not enforced | 🟡 | Medium | Priv account without 2FA | 2FA available, optional | P5 | OPEN |
| 15 | API keys never expire by date | 🟡 | Medium | Long-lived leaked key valid forever | Manual revoke + scopes | P8* | OPEN |
| 16 | Connector testing ungated (SSRF/egress) | 🟡 | Low–Med | Server-side request to attacker host | super_admin-only | P6 | OPEN |
| 17 | Zero frontend tests | 🟡 | High | Auth/data UI regressions ship | Manual QA | P10 | OPEN |
| 18 | No metrics → blind incident response | 🟡 | High | Slow MTTR | JSON logs + request_id | P9 | OPEN |
| 19 | No incident runbooks | 🟡 | High | Inconsistent incident handling | Tribal knowledge | P4/P9 | OPEN |
| 20 | No CI gate for isolation/AI/config | 🟡 | Medium | Safety regressions merge silently | Partial CI | P13 | OPEN |
| 21 | No tenant data export/delete-on-request | 🟡 | Medium | Privacy/contract non-compliance | Manual DB ops | P12 | OPEN |
| 22 | `render.yaml` prod-env + demo behavior contradiction | 🟡 | High (if used) | Confusing/unsafe deploy | None | P2 | OPEN |
| 23 | Forecast trainer / cache warmer always-on in API | 🟢 | Medium | CPU contention on small hosts | `forecast_trainer_enabled` flag | P2 | OPEN |
| 24 | No image/dependency scanning in CI | 🟢 | Medium | Vulnerable deps ship | None | P13 | OPEN |
| 25 | No data-freshness signal to users | 🟢 | Low | Stale data mistaken for live | SSE timestamps | P3/P11 | OPEN |
| 26 | Employee seeder runs on every API boot | 🟢 | Low | Redundant work, log noise | try/except wrapped | P2 | OPEN |
| 27 | No rollback procedure documented | 🟢 | Medium | Slow recovery from bad release | Git revert (manual) | P4 | OPEN |
| 28 | Migration runner has no fresh-vs-existing CI proof | 🟢 | Medium | Migration breaks unnoticed | Idempotent design | P13 | OPEN |
| 29 | No alert thresholds defined | 🟢 | Medium | Incidents noticed late | Optional webhook/Sentry | P9 | OPEN |
| 30 | Legal/privacy docs absent | 🟢 | Low | No customer trust package | None | P12 | OPEN |

\* P8 (and P7) deferred — see `KNOWN_LIMITATIONS.md`. Only the API-key `expires_at` carve-out of P8 is attempted this cycle.

## How to read severity here
Severity assumes a **real pilot with ≥1 paying tenant on multi-replica infra**. On the current single-box demo, several "Critical" items (3, 5) are latent rather than active — but they become active the moment the system is deployed as intended, which is the entire point of this program.
