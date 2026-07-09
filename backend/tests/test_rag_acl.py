"""Unit tests for the RBAC retrieval filter (RAG-5). Pure logic — no DB.
The security boundary for Sage retrieval; treat failures as security bugs."""
from app.services.rag.acl import allowed_sensitivities, build_acl_filter


def test_sensitivity_ladder_by_role():
    assert allowed_sensitivities("store_manager") == ["public", "internal"]
    assert allowed_sensitivities("analyst") == ["public", "internal"]
    assert "restricted" in allowed_sensitivities("super_admin")
    assert "restricted" in allowed_sensitivities("regional_manager")


def test_unknown_role_denied_to_public_floor():
    # deny-by-default: an unrecognized role sees only public content
    assert allowed_sensitivities("mystery") == ["public"]
    assert allowed_sensitivities(None) == ["public"]


def test_super_admin_empty_stores_has_no_store_clause():
    # allowed_stores == [] means NO restriction (see all), not "see nothing"
    f = build_acl_filter(1, "super_admin", [])
    assert "store_scope" not in f.where_sql
    assert f.params["acl_tid"] == 1


def test_store_scope_clause_present_when_scoped():
    f = build_acl_filter(1, "store_manager", [3, 5])
    assert "store_scope" in f.where_sql
    assert f.params["acl_stores"] == [3, 5]
    assert f.params["acl_role"] == "store_manager"
    assert f.params["acl_sens"] == ["public", "internal"]


def test_tenant_always_filtered():
    f = build_acl_filter(7, "analyst", [1])
    assert "tenant_id = :acl_tid" in f.where_sql
    assert f.params["acl_tid"] == 7


def test_cache_hash_is_store_order_independent():
    a = build_acl_filter(1, "store_manager", [3, 5]).filter_hash
    b = build_acl_filter(1, "store_manager", [5, 3]).filter_hash
    assert a == b


def test_cache_hash_changes_with_authorization():
    base = build_acl_filter(1, "store_manager", [3, 5]).filter_hash
    assert build_acl_filter(1, "regional_manager", [3, 5]).filter_hash != base  # role
    assert build_acl_filter(2, "store_manager", [3, 5]).filter_hash != base     # tenant
    assert build_acl_filter(1, "store_manager", [3]).filter_hash != base        # stores


def test_param_prefix_and_alias_customizable():
    f = build_acl_filter(1, "store_manager", [3], alias="doc", param_prefix="x")
    assert "doc.tenant_id = :x_tid" in f.where_sql
    assert "x_tid" in f.params
