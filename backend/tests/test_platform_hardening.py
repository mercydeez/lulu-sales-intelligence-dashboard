"""B5 — the platform-operator boundary applied to the cross-tenant surfaces.

The gap: every self-signup tenant owner is created super_admin
(services/tenant_provisioning.py), so a `role == 'super_admin'` check on a
cross-tenant endpoint let ANY customer list all tenants, read platform MRR,
create tenants, and drive provisioning. These tests pin the fix:

  - cross-tenant routes gate on require_platform_developer (the dependency,
    not a same-named stub),
  - tenant-scoped routes (branding, usage, billing profile) stay reachable by
    tenant admins and never acquire the platform gate,
  - the super_admin role check is gone from every hardened endpoint.

Structural (`_code`, ast-stripped source) in the house style of
test_provisioning.py; the dependency's own behaviour (403 for super_admins
without the flag, allowlist AND-gate) is covered in test_platform_access.py.
"""
import ast
import inspect
import textwrap

from app.routes import provisioning as provisioning_routes
from app.routes import tenants as tenants_routes
from app.services import platform_access as pa


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# Cross-tenant operator surfaces: each one reads or writes OTHER tenants' rows.
CROSS_TENANT = (
    tenants_routes.list_tenants,        # the entire customer list
    tenants_routes.platform_metrics,    # counts + MRR across tenants
    tenants_routes.create_tenant,       # mints new tenants
    tenants_routes.change_status,       # lifecycle of any tenant
    tenants_routes.list_status_events,  # any tenant's lifecycle history
    tenants_routes.list_notes,          # operator notes about any tenant
    tenants_routes.add_note,
)

# Tenant self-service: bound to current_user.tenant_id, must stay role-gated.
TENANT_SCOPED = (
    tenants_routes.update_branding,
    tenants_routes.tenant_usage,
    tenants_routes.tenant_usage_period,
    tenants_routes.get_billing_profile,
    tenants_routes.upsert_billing_profile,
)

# Provisioning is pure control-plane: every route is cross-tenant.
PROVISIONING = (
    provisioning_routes.list_provisioning,
    provisioning_routes.get_one,
    provisioning_routes.request_tier,
    provisioning_routes.provision,
    provisioning_routes.deprovision,
)


# --------------------------------------------------------------------------
# (a) Cross-tenant tenants.py endpoints gate on the platform boundary.
# --------------------------------------------------------------------------

def test_cross_tenant_endpoints_depend_on_require_platform_developer():
    for fn in CROSS_TENANT:
        assert "Depends(require_platform_developer)" in _code(fn), fn.__name__


def test_the_dependency_is_the_real_one_not_a_lookalike():
    """Both routers must import THE platform_access dependency — a same-named
    local re-implementation would defeat the boundary silently."""
    assert tenants_routes.require_platform_developer is pa.require_platform_developer
    assert provisioning_routes.require_platform_developer is pa.require_platform_developer


# --------------------------------------------------------------------------
# (b) Tenant-scoped endpoints stay tenant-reachable.
# --------------------------------------------------------------------------

def test_tenant_scoped_endpoints_do_not_acquire_the_platform_gate():
    for fn in TENANT_SCOPED:
        code = _code(fn)
        assert "require_platform_developer" not in code, fn.__name__
        # Still authenticated + role-checked tenant self-service.
        assert "Depends(get_current_user)" in code, fn.__name__
        assert "'super_admin', 'admin'" in code, fn.__name__


def test_tenant_scoped_endpoints_stay_bound_to_the_callers_tenant():
    """The self-service routes must keep reading the caller's tenant_id, never a
    path/query tenant id — that is what makes them safe to leave role-gated."""
    for fn in TENANT_SCOPED:
        assert "current_user.get('tenant_id')" in _code(fn), fn.__name__


# --------------------------------------------------------------------------
# (c) Provisioning is platform-developer-only, end to end.
# --------------------------------------------------------------------------

def test_every_provisioning_route_gates_on_the_platform_boundary():
    for fn in PROVISIONING:
        assert "Depends(require_platform_developer)" in _code(fn), fn.__name__


def test_provisioning_no_longer_defines_or_calls_the_role_helper():
    src = inspect.getsource(provisioning_routes)
    assert "_require_super_admin" not in src


# --------------------------------------------------------------------------
# (d) Negative control: the super_admin role is no longer a gate anywhere
#     on the hardened endpoints.
# --------------------------------------------------------------------------

def test_super_admin_role_is_not_a_gate_on_any_hardened_endpoint():
    for fn in (*CROSS_TENANT, *PROVISIONING):
        code = _code(fn)
        # ast.unparse normalises string literals to single quotes.
        assert "'super_admin'" not in code, fn.__name__
        assert "_require_super_admin" not in code, fn.__name__
        assert "Depends(get_current_user)" not in code, fn.__name__


def test_hardened_routes_still_require_authentication():
    """The dependency chains through get_current_user, so anonymous callers get
    401 before any handler runs — the hardening must not have unmounted them."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/tenants").status_code == 401
    assert client.get("/api/tenants/metrics").status_code == 401
    assert client.get("/api/admin/provisioning").status_code == 401
