# Runbook — Tenant Data Deletion (erasure on request)

> Operator procedure for executing a tenant **delete-on-request**. Deletions are
> **human-approved and never automated** by the API. The `/api/data-rights`
> endpoints only *record* a request; this runbook is how an operator carries it
> out safely and reversibly.

## Trigger

A `data_requests` row with `kind = 'delete'` and `status = 'pending'` (filed via
`POST /api/data-rights/requests`, audited as `data_request_filed`).

## Preconditions

- Confirm the requester is a verified admin **of that tenant** (check
  `requested_by` / `requested_email` against `users` for the same `tenant_id`).
- Confirm there is no legal hold or retention obligation on the tenant's data.
- Take a fresh backup first (`docs/production/BACKUP_RESTORE.md`) — this gives the
  reversible review window.

## Procedure

1. **Approve**: set the request `status = 'approved'`, record `reviewed_by` and a
   `reason`. Announce the review window (default 7 days) to the requester.
2. **Review window**: during this window the deletion can be cancelled
   (`status = 'cancelled'`). This guards against mistaken/compromised requests.
3. **Execute** (after the window): within a transaction, delete the tenant's rows
   from every tenant-stamped table (the same set discovered by
   `data_rights_service._tenant_tables`), children before parents to respect FKs.
   Deactivate (do not orphan) the tenant's users and revoke all API keys.
4. **Backups**: schedule targeted scrubbing or allow backup expiry per the
   retention policy so the data does not persist indefinitely in backups. Record
   the expiry date.
5. **Close**: set `status = 'completed'`, record completion time. The
   `data_requests` audit row itself is retained as proof the request was handled.

## Verification

- `SELECT count(*)` per tenant table for the deleted `tenant_id` returns 0.
- The tenant's users can no longer authenticate; all its API keys are revoked.
- A new export for that tenant returns empty tables.

## Notes

- **Never** run an ad-hoc `DELETE` outside a transaction or without a fresh backup.
- Cross-tenant safety: the `WHERE tenant_id = :tid` filter is mandatory on every
  statement; double-check the bound id before executing.
