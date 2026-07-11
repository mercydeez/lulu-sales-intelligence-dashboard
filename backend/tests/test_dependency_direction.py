"""Architectural regression guards: dependency direction + import-path compat.

The July 2026 simplification pass extracted two cross-cutting layers out of
route modules:

  * app.auth_deps          <- was app.routes.auth (get_current_user & friends)
  * app.services.kpi_service    <- was app.routes.kpis (compute_and_cache_kpis)
  * app.services.forecast_lab   <- was app.routes.analytics (Forecast Lab compute)

These tests pin the two invariants that pass established, so the coupling
cannot silently regrow:

  1. DIRECTION — services never import routes; routes never import other
     routes (the registry is the single declared hub).
  2. COMPAT — the old import paths still work and resolve to the SAME objects
     (identity matters: FastAPI dependency_overrides are keyed by function
     identity, so a wrapper instead of a re-export would break every override).

Pure AST/imports — no DB, no HTTP.
"""
import ast
import os

_HERE = os.path.dirname(__file__)
_APP = os.path.join(os.path.dirname(_HERE), "app")


def _py_modules(subdir: str):
    root = os.path.join(_APP, subdir)
    for dirpath, _, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _imported_modules(path: str):
    """Every module named by ANY import in the file (module-level or nested —
    a function-scope import of a route from a service is still wrong-direction
    coupling, just deferred)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_services_never_import_routes():
    offenders = []
    for path in list(_py_modules("services")) + list(_py_modules("commands")):
        for mod in _imported_modules(path):
            if mod == "app.routes" or mod.startswith("app.routes."):
                offenders.append(f"{os.path.relpath(path, _APP)} -> {mod}")
    assert not offenders, (
        "services/commands must not depend on the web layer; move the shared "
        f"logic into a service module instead: {offenders}"
    )


def test_routes_never_import_other_routes():
    # registry.py is the one declared hub that names every router.
    offenders = []
    for path in _py_modules("routes"):
        name = os.path.basename(path)
        if name in ("registry.py", "__init__.py"):
            continue
        own = f"app.routes.{name[:-3]}"
        for mod in _imported_modules(path):
            if (mod == "app.routes" or mod.startswith("app.routes.")) and mod != own:
                offenders.append(f"{os.path.relpath(path, _APP)} -> {mod}")
    assert not offenders, (
        "route modules must not import each other (shared code belongs in "
        f"app.auth_deps or app.services.*): {offenders}"
    )


def test_routes_package_init_is_import_free():
    tree = ast.parse(open(os.path.join(_APP, "routes", "__init__.py"), encoding="utf-8").read())
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not imports, "app/routes/__init__.py must stay import-free (no forced import order)"


def test_auth_deps_below_the_web_layer():
    path = os.path.join(_APP, "auth_deps.py")
    for mod in _imported_modules(path):
        assert not mod.startswith("app.routes"), f"app.auth_deps must not import routes (got {mod})"


def test_old_auth_import_path_still_works_and_is_identical():
    from app import auth_deps
    from app.routes import auth as auth_routes

    for name in (
        "get_current_user", "get_current_user_optional",
        "require_role", "require_permission",
        "can_access_store", "get_accessible_store_ids", "filter_by_user_stores",
        "get_current_user_from_ticket",
        "set_auth_cookies", "clear_auth_cookies",
        "ACCESS_COOKIE", "REFRESH_COOKIE",
        "LoginResponse", "CurrentUser", "security",
    ):
        assert getattr(auth_routes, name) is getattr(auth_deps, name), (
            f"app.routes.auth.{name} must re-export the exact app.auth_deps object "
            "(identity, not a copy — dependency_overrides are keyed on it)"
        )


def test_old_kpi_and_analytics_import_paths_still_work_and_are_identical():
    from app.services import kpi_service, forecast_lab
    from app.routes import kpis as kpis_routes
    from app.routes import analytics as analytics_routes

    for name in ("compute_and_cache_kpis", "_serialize_kpi_dates",
                 "_parse_kpi_dates", "kpis_cache_key", "_safe_defaults", "_NEEDS_COST"):
        assert getattr(kpis_routes, name) is getattr(kpi_service, name)

    for name in ("compute_and_cache_model_metrics", "_compute_model_metrics_sync",
                 "_empty_model_metrics", "model_metrics_cache_key",
                 "_try_claim_metrics_warm", "_release_metrics_warm",
                 "compute_and_cache_store_distribution", "store_distribution_cache_key",
                 "_warm_model_metrics_in_background", "MODEL_METRICS_TTL"):
        assert getattr(analytics_routes, name) is getattr(forecast_lab, name)
