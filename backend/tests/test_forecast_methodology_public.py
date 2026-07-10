"""E7-2 — the public forecast-methodology publication.

"Ramadan-accurate, and we show our error rate." The endpoint is unauthenticated
on purpose: a prospect must be able to check our arithmetic before trusting us
with their data. That makes two properties load-bearing:

  1. it can leak NOTHING about any tenant, and
  2. it must never publish a Ramadan number for a season it did not measure.
"""
import inspect

from app.routes import monitoring


def test_the_endpoint_takes_no_authentication_dependency():
    """If this ever grows a Depends(get_current_user), it stops being a
    publication and becomes a private report."""
    sig = inspect.signature(monitoring.forecast_methodology)
    assert not sig.parameters, "the public methodology endpoint must take no dependencies"


def _code_without_docstring(fn) -> str:
    """The function's CODE. Its docstring names the things it refuses to publish,
    so a naive substring check over the whole source would fail on the prose."""
    import ast
    import textwrap

    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    # Strip decorators too — the route path contains the word "forecast".
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def test_only_whitelisted_anonymous_fields_are_published():
    """A whitelist, not a blacklist. The model-metrics payload it reads from also
    carries revenue, per-store heatmaps and item accuracy — those stay private by
    never being copied out."""
    code = _code_without_docstring(monitoring.forecast_methodology)

    allowed = {
        "forecasting_version", "baseline_model",
        "baseline_mape", "baseline_wape",
        "selected_model", "selected_model_mape", "selected_model_wape",
        "wape_improvement_vs_baseline_pct",
        "ramadan_accuracy", "ramadan_mape", "ramadan_wape",
        "ramadan_eval_days", "ramadan_accuracy_reason",
        "calendar_feature_summary", "methodology_note",
    }
    for field in allowed:
        assert field in code

    # Nothing that identifies a tenant or quantifies their business.
    for forbidden in ("revenue", "heatmap", "leaderboard", "item_accuracy",
                      "business_impact", "store_name", "tenant_name", "accuracy_trend"):
        assert forbidden not in code, f"public methodology must not publish {forbidden}"


def test_a_cold_cache_publishes_warming_not_a_stale_number():
    src = inspect.getsource(monitoring.forecast_methodology)
    assert '"status": "warming"' in src
    assert 'cached.get("status") != "ready"' in src


def test_it_reads_the_reference_tenant_not_a_customer():
    src = inspect.getsource(monitoring.forecast_methodology)
    assert "s.demo_tenant_id" in src
    assert '"dataset"' in src


def test_the_publication_can_be_withheld():
    src = inspect.getsource(monitoring.forecast_methodology)
    assert "forecast_methodology_public" in src
    assert "status_code=404" in src

    from app.config import Settings
    s = Settings(environment="testing",
                 jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                 secret_key="test-app-secret-key-minimum-32-chars-for-testing")
    assert s.forecast_methodology_public is True   # published by default


def test_ramadan_accuracy_is_never_extrapolated():
    """The reason field exists precisely so a missing season is stated, not filled in."""
    src = inspect.getsource(monitoring.forecast_methodology)
    assert '"ramadan_accuracy_reason"' in src
    assert "did not measure" in src or "never measured" in src


def test_the_public_page_is_reachable_signed_out():
    """ClientLayout's openPaths decide what renders without a login."""
    import os
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    layout = os.path.join(repo, "frontend", "src", "components", "ClientLayout.tsx")
    with open(layout, encoding="utf-8") as fh:
        src = fh.read()
    assert "'/methodology'" in src
    assert "openPaths" in src
