# Data-Source Security

"Connect your database" lets a super-admin register an external Postgres source the
dashboard reads from instead of the synthetic demo. This is powerful and is hardened
on three axes: tenant isolation, credential handling, and connector egress.

## Tenant isolation (fixed in Phase 6)

Previously `get_active_source()` / `set_active()` / `delete_source()` /
`get_source_with_connection()` / `record_test_result()` operated **globally by id**,
and the "one active source" unique index was global — so one tenant could read or
flip another tenant's active source. Now:

- Every operation takes and filters by `tenant_id` (`services/data_sources.py`).
- `set_active` clears and sets the active flag **within the tenant only**.
- Migration **037** replaces the global `uq_data_sources_one_active` with a
  per-tenant partial-unique index `(tenant_id) WHERE is_active` — each tenant has
  exactly one active source, independently.
- The read path (`source_adapters.active_external_source`) resolves the active
  source from the request's `tenant_context`, never globally.
- Postgres RLS (migration 031, `tenant_id = current_tenant_id()`) is the second
  layer when `USE_RLS_ROLE` is on.

Regression tests: `tests/test_data_source_isolation.py`.

## Credentials

- Connection strings are encrypted at rest (Fernet, key derived from `SECRET_KEY`).
- `_row_public()` strips `connection_enc` from every API response — the raw or
  decrypted connection is **never** serialized to a client or logged. The decrypted
  value is handed only to the internal adapter that opens the connection.

## Connector egress (SSRF surface)

Testing a connection opens an outbound database connection to an operator-supplied
host — an SSRF/egress surface. Therefore:

- Connector testing (`POST /test`, `POST /{id}/test`) is gated by
  `ENABLE_DATA_SOURCE_CONNECTORS`, **off by default in production**. Disabled →
  `403`.
- All management actions require the `super_admin` role.
- SQL identifiers in the column mapping are validated + quoted (`_safe_identifier`);
  the measure is units or `units × price`, never arbitrary SQL.

## Audit

`data_source_created`, `data_source_tested`, `data_source_activated`,
`data_source_deleted` are recorded as security events (tenant + actor + detail).
