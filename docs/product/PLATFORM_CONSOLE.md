# Platform Console — Per-Tenant Customization, Bespoke Requests, and Operator Tooling

> Internal tooling for the vendor's own engineers, not a customer surface. Companion to
> `../../TEAM_OWNERSHIP.md` (who operates it), `DEMO_VS_REAL_DATA.md` (the honesty
> contract it inherits), and `IMPROVEMENT_ROADMAP.md` (where its outputs feed the
> product plan). Code: `backend/app/services/platform_access.py`,
> `backend/app/services/customization.py`, `database/migrations/072_krishna_platform_developer.sql`.

---

## 1. What it is

Retail Intelligence sells to retailers whose needs never fit a pricing grid exactly.
The Platform Console is the internal answer to that — the **"Rolls-Royce" posture**:

> A client can ask for anything. If the catalog already covers it, we turn the knob
> for their tenant. If it doesn't, the ask becomes a **tracked bespoke request** with
> an owner and a status — never a verbal promise that evaporates.

Three moving parts implement that posture:

1. **The customization catalog** — every per-tenant knob the product supports, in one
   typed registry (`FLAG_CATALOG` in `services/customization.py`), with per-tenant
   overrides stored under the `customizations` namespace of `tenants.settings` (JSONB).
2. **The bespoke-request ledger** — asks the catalog can't satisfy, tracked from
   `requested` through `delivered` (or honestly `declined`, with the reason recorded).
3. **The Atelier advisor** — paste a client's plain-language need; it maps the ask
   onto catalog knobs it can satisfy today and files the gaps as bespoke drafts.

Plus an **ops/readiness panel** so the person turning knobs can see, in the same
place, what the platform can actually deliver right now (provider readiness, quotas,
security-event counts) and run the two routine demo-hygiene actions.

---

## 2. Access policy — who should be given access

**Platform developers only: the vendor's own engineers.** Not tenant admins, not
customers, and (in v1) not support staff. Today that is the three-person platform
team — Atharva, Krishna, Yash — seeded by migration `072_krishna_platform_developer.sql`.

### Why `super_admin` cannot be the gate

`super_admin` is a **tenant** role. Every self-signup owner is created `super_admin`
of their own workspace (`services/tenant_provisioning.py`) — so "is super_admin" is
true of every customer who signed up five minutes ago. A console that lists tenants,
edits their configuration, and resets demo data is a **cross-tenant** surface; gating
it on a role every tenant owner holds would hand it to every customer. The boundary
has to be something a tenant can never grant itself.

### The mechanics (fail-closed, both sides)

Access requires **both** of the following (`services/platform_access.py`):

```
usable = users.is_platform_developer  AND  (allowlist empty OR email in PLATFORM_DEVELOPER_EMAILS)
```

- **DB flag** — `users.is_platform_developer` (migration 072). Additive: a platform
  developer keeps their normal role for everything else. Not a new enum role, so
  SSO/SCIM role clamping and permission aggregation are untouched.
- **Env allowlist** — `PLATFORM_DEVELOPER_EMAILS` (comma-separated, case-insensitive).
  When set, it AND-gates the flag: a tampered DB row alone cannot mint platform
  access. Defence in depth for production.
- **Fail-closed on both sides.** No flag → refused, regardless of role. Allowlist
  configured but email absent → refused, even with the flag. There is no "fail open
  if unsure" path anywhere in this check.
- **Grants are an operator action** — a migration or a deliberate SQL `UPDATE` by
  someone with DB access, plus (in production) an allowlist edit and redeploy.
  There is no API, no UI, and no self-service path that sets the flag. That is by
  design; do not add one.

### Everything is audited — including refusals

Every console mutation *and every refused access attempt* writes a `security_events`
row (`services/security_events.py :: record_event`). The console's event vocabulary:

| Event type | When |
|---|---|
| `platform_access_denied` | Anyone without the boundary hits a console route (recorded as category `threat`) |
| `customization_changed` / `customization_cleared` | A tenant override is set / reverted |
| `bespoke_request_created` / `bespoke_request_updated` | Ledger writes, including status moves and declines |
| `atelier_suggestion` | The advisor produced suggestions for a client need |
| `ops_demo_reset` / `ops_cache_flush` | An operator ran a demo-hygiene action |

The refusal itself never depends on the audit write succeeding (best-effort event,
guaranteed 403).

### Explicitly out of scope for v1 (roadmap, not promises)

- **Tenant-visible bespoke status** — customers cannot yet see the state of their own
  requests in-product. Planned; until then, status updates travel by account manager.
- **A support-staff read-only tier** — v1 is binary (platform developer or nothing).
  A read-only tier for support is a roadmap item, not an undocumented loophole.

---

## 3. The surfaces

### 3.1 Customization catalog

One typed catalog of 21 keys across five categories — `modules.*` (forecasting,
promotions, procurement, inventory, reports, diagnostics), `assistant.*` (`ai_chat`,
`voice`, `mode`), `interface.*` (`default_theme`, `compact_tables`, `landing_page`),
`integrations.*` (`public_api`, `webhooks`, `pos`, `payments`, `einvoicing`,
`imports_scheduled`), and `limits.*` (`sage_messages_per_day`, `export_rows`,
`api_rate_multiplier`).

**Resolution is layered, most specific wins:** catalog default → plan gate → tenant
override. The console shows each effective value with a **source badge** —
`default` (nothing set), `plan` (the tenant's plan decided it), `override` (a bespoke
exception was recorded for this tenant).

**Plan-as-floor semantics.** A key's `plan_min` names the lowest plan
(`free < starter < growth < enterprise`, mirroring `services/billing.py`) that may
enable or raise it. An override is a bespoke exception **on top of a qualifying
plan** — it is never a way to bypass what the plan doesn't include. `set_override`
refuses values the tenant's plan doesn't reach.

**The honesty rule (load-bearing).** Every catalog key declares `enforced_by`: the
code path that actually honours it (e.g. `routes/ai.py require_ai_chat`,
`routes/experience.py`, `routes/public_api.py`) — or the literal string `'planned'`
for knobs whose enforcement has not landed yet. A flag nothing enforces is a Potemkin
toggle, so the console UI **must render `'planned'` keys as "not yet enforced"** —
visibly, next to the toggle. Turning a `planned` knob records intent; it does not
change product behaviour yet, and we say so rather than letting an operator promise
a client something the code doesn't do.

Overrides live only under `tenants.settings -> 'customizations'`; nothing else may
write that namespace, and writes merge rather than clobber the column.

### 3.2 Bespoke-request ledger

Asks the catalog can't satisfy become ledger rows with a lifecycle:

```
requested → scoped → approved → building → delivered
                └────────────→ declined (with reason)
```

Two **database CHECK constraints** keep the statuses honest — a row cannot claim an
end-state without its proof:

- `delivered` requires `delivered_at` — no "done" without a timestamp.
- `declined` requires `scoping_notes` — no silent no; the reason is recorded where
  the requester's account team can read it back.

Every create and update is audited (`bespoke_request_created` / `bespoke_request_updated`).

### 3.3 Atelier advisor

Describe a client's need in plain language; Atelier answers with (a) catalog keys
that satisfy parts of it today — turnable now — and (b) the gaps, pre-drafted as
bespoke requests for a human to review and file. It prompts from `FLAG_CATALOG`
itself, so it can only suggest knobs that exist.

**Engine honesty:** every response is labeled with the engine that produced it —
`'llm'` when the local model answered (Ollama `llama3.2`, on-box via `OLLAMA_URL`;
no tenant data leaves the deployment), or `'rules'` when the LLM was unavailable and
the deterministic keyword fallback ran. A rules-based answer is never dressed up as
AI. Suggestions are drafts for a human; Atelier files nothing on its own beyond the
audited `atelier_suggestion` event.

### 3.4 Ops & readiness panel

The context an operator needs *before* promising anything:

- **Provider readiness** for payments (`services/payments.py`), POS connectors
  (`services/pos_connectors.py`), and e-invoicing (`services/einvoicing.py`) — each
  reports which providers are in its `IMPLEMENTED_PROVIDERS` / `IMPLEMENTED_VENDORS`
  set and credentialed, versus merely recognised. Recognised-but-unimplemented is
  shown as exactly that.
- **Quota enforcement** — plan limits and usage (`services/plan_limits.py`,
  `services/usage_metering.py`) so an override conversation starts from real numbers.
- **Security-warning counts only.** The panel shows `security_events` *counts* by
  type/severity — never event payloads, tokens, or anything secret-shaped. Detail
  inspection belongs in the DB with DBA access, not in a browser tab.
- **Actions:** demo-tenant reset (`services/demo_reset.py`) and cache flush — both
  audited (`ops_demo_reset`, `ops_cache_flush`).

---

## 4. Operating notes

- **Set `PLATFORM_DEVELOPER_EMAILS` in production.** The DB flag alone is acceptable
  for dev; production should always AND-gate on the allowlist so a compromised DB
  row cannot mint console access.
- **Re-login after a grant.** `is_platform_developer` rides the user dict established
  at login; a freshly granted (or revoked) user sees the change at their next login,
  not mid-session. Revocations that must take effect immediately should also
  invalidate the user's session.
- **Granting:** `UPDATE users SET is_platform_developer = TRUE WHERE email = ...` via
  a migration (see 072 for the pattern) — and add the email to the allowlist.
  Revoke by doing the reverse of both.
- The customization resolution engine ships behind a pinned contract
  (`resolve_effective` / `flag_value` / `set_override` in `services/customization.py`);
  enforcement call sites treat engine errors as "no override" (fail-open on
  infrastructure, fall back to catalog defaults) while the access gate in front of
  the console stays fail-closed. Infrastructure hiccups degrade to defaults; access
  never degrades to open.
