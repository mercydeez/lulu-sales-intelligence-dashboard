# Runbook — Data export & deletion (PDPL data-subject rights)

**Owner:** Krishna (Platform, Data & Services)

Under the UAE Personal Data Protection Law (PDPL) a tenant has the right to **access**
(export) and **erasure** (delete) of their personal data. This runbook is the
operational procedure. It pairs with `docs/runbooks/DATA_RESIDENCY.md` — export copies
must stay in the same UAE region as the source data.

The API lives under **`/api/data-rights`** (`backend/app/routes/data_rights.py`,
mounted in `routes/registry.py`), backed by `services/data_rights_service.py`. All
three endpoints require an **admin** of the calling tenant and are strictly
tenant-scoped: `tenant_id` is taken from the caller's token, so an admin can only ever
export or request against their own tenant.

---

## 1. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/data-rights/export` | tenant admin | Generate & download the full tenant export now (JSON attachment) |
| `POST` | `/api/data-rights/requests` | tenant admin | File an export or **delete** request (delete is human-reviewed) |
| `GET` | `/api/data-rights/requests` | tenant admin | List this tenant's filed requests + status |

## 2. Export (data access)

`GET /api/data-rights/export` streams a JSON attachment
(`tenant-<id>-export.json`) built by `export_tenant_data()`, which walks every
tenant-scoped table and dumps that tenant's rows. Each export:

- is recorded as a `tenant_data_exported` security event (with the table list as
  evidence), and
- is metered as a `data_rights` export for billing/quota (Phase 3).

```bash
# As a tenant admin (e.g. krishna@retaildemo.app / Demo@2026!):
TOKEN=... # from POST /api/auth/login
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://api.yourdomain.com/api/data-rights/export -o tenant-export.json
```

**Residency note:** save and transmit the export inside the UAE region. Do not email or
upload it to an out-of-region location — that would defeat the residency posture.

## 3. Deletion (erasure)

Deletion is **not** self-service — it is filed as a request and executed by an operator
after human review, so an admin cannot irreversibly wipe a tenant with one call:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"delete","scope":"all"}' \
  https://api.yourdomain.com/api/data-rights/requests
```

The response confirms the request is recorded and reviewed by an operator. Filing emits
a `data_request_filed` security event (kind + request id as evidence). `kind` may be
`export` or `delete`; `scope` is a free-form descriptor of what to erase.

The **operator delete procedure** (approve → review window → execute → scrub backups →
close) is documented in full in **`docs/runbooks/DATA_DELETION.md`** — follow it for any
`kind='delete'` request. The one residency-specific addition: take the pre-delete backup
**in the same UAE region** and never restore it out-of-region.

## 4. Verify a request's status

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://api.yourdomain.com/api/data-rights/requests | jq '.requests'
```

## 5. Evidence to retain

- The `tenant_data_exported` / `data_request_filed` security events (immutable audit).
- For deletions: the pre-delete backup id, the operator who approved, and the
  completion event.
- Confirmation that all copies (export files, backups referenced) remained in-region.

## 6. Related

- `docs/runbooks/DATA_DELETION.md` — full operator erasure procedure.
- `docs/runbooks/DATA_RESIDENCY.md` — keep every export/backup in the UAE region.
- `docs/runbooks/BACKUP_AND_RESTORE.md` — pre-delete backup + restore.
- `backend/app/routes/data_rights.py`, `backend/app/services/data_rights_service.py`.
