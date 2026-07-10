"""E6-6 — the public API version contract.

Two things are load-bearing here:

  1. No public route may be added without a version segment. The guard is
     structural (it reads the router), not a convention in a doc nobody reads.
  2. Deprecation is announced before it is enforced, and enforcement is real —
     after the sunset date the version stops answering. A `Sunset` header we do
     not honour would teach integrators to ignore the next one.

The lifecycle is pure and takes `today`, so we can test 2027 without waiting.
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.routes import public_api
from app.services import api_versioning as av


# --------------------------------------------------------------------------
# 1. Structural guard: every public route is versioned.
# --------------------------------------------------------------------------

def _public_route_paths():
    return [r.path for r in public_api.router.routes]


def test_every_public_route_carries_a_version_segment():
    """A route mounted at /api/public/<thing> instead of /api/public/v1/<thing>
    is an unversioned public contract we can never change. Catch it here."""
    offenders = [
        p for p in _public_route_paths()
        if p not in av.UNVERSIONED_PUBLIC_PATHS and av.version_from_path(f"/api/public{p}") is None
    ]
    assert not offenders, f"unversioned public routes: {offenders}"


def test_the_guard_would_actually_catch_an_unversioned_route():
    """Negative control. Without this, the test above passes trivially if
    `version_from_path` ever starts returning a truthy value for everything."""
    assert av.version_from_path("/api/public/kpis") is None          # would be caught
    assert av.version_from_path("/api/public/v1/kpis") == "v1"       # would not
    assert av.version_from_path("/api/public/v2/kpis") == "v2"
    assert av.version_from_path("/api/public/versions") is None
    # Not the public surface at all.
    assert av.version_from_path("/api/kpis") is None


def test_discovery_is_reachable_without_a_version():
    assert "/versions" in _public_route_paths()
    assert "/versions" in av.UNVERSIONED_PUBLIC_PATHS


def test_the_version_constant_matches_what_is_actually_mounted():
    """One constant, so the decorators cannot drift from the advertised version."""
    versioned = [p for p in _public_route_paths() if p not in av.UNVERSIONED_PUBLIC_PATHS]
    assert versioned, "expected at least one versioned public route"
    for p in versioned:
        assert p.startswith(f"/{av.PUBLIC_API_VERSION}/")
    assert av.PUBLIC_API_VERSION in av.SUPPORTED_PUBLIC_VERSIONS


# --------------------------------------------------------------------------
# 2. The lifecycle state machine.
# --------------------------------------------------------------------------

def _settings(**kw):
    return Settings(
        environment="testing",
        jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
        secret_key="test-app-secret-key-minimum-32-chars-for-testing",
        **kw,
    )


def _patch_settings(monkeypatch, s):
    monkeypatch.setattr(av, "get_settings", lambda: s)


def test_today_v1_is_current_and_silent(monkeypatch):
    """The machinery is live, not flagged off — it is inert because no version
    carries a lifecycle date. This is the shipped default."""
    s = _settings()
    assert s.public_api_v1_deprecated_on is None
    assert s.public_api_v1_sunset_on is None
    _patch_settings(monkeypatch, s)

    state = av.lifecycle("v1", today=date(2026, 7, 10))
    assert state["status"] == "current"
    assert state["deprecated_on"] is None and state["sunset_on"] is None


def test_a_future_deprecation_is_published_before_it_bites(monkeypatch):
    """An integrator must be able to SEE a deprecation coming, so the announced
    date is published while the version is still 'current'."""
    s = _settings(public_api_v1_deprecated_on=date(2027, 1, 31),
                  public_api_v1_sunset_on=date(2027, 7, 31))
    _patch_settings(monkeypatch, s)

    before = av.lifecycle("v1", today=date(2026, 12, 1))
    assert before["status"] == "current"
    assert before["deprecated_on"] == "2027-01-31"     # announced, not yet in effect
    assert before["sunset_on"] == "2027-07-31"


def test_status_walks_current_then_deprecated_then_sunset(monkeypatch):
    s = _settings(public_api_v1_deprecated_on=date(2027, 1, 31),
                  public_api_v1_sunset_on=date(2027, 7, 31))
    _patch_settings(monkeypatch, s)

    assert av.lifecycle("v1", today=date(2027, 1, 30))["status"] == "current"
    assert av.lifecycle("v1", today=date(2027, 1, 31))["status"] == "deprecated"   # inclusive
    assert av.lifecycle("v1", today=date(2027, 7, 30))["status"] == "deprecated"
    assert av.lifecycle("v1", today=date(2027, 7, 31))["status"] == "sunset"       # inclusive
    assert av.lifecycle("v1", today=date(2028, 1, 1))["status"] == "sunset"


def test_http_date_is_an_imf_fixdate():
    """RFC 9745 and RFC 8594 both require an IMF-fixdate, not an ISO date."""
    assert av._http_date(date(2027, 1, 31)) == "Sun, 31 Jan 2027 00:00:00 GMT"


# --------------------------------------------------------------------------
# 3. The dependency: headers, then refusal.
# --------------------------------------------------------------------------

class _Req:
    def __init__(self, path):
        self.url = type("U", (), {"path": path})()


class _Resp:
    def __init__(self):
        self.headers = {}


@pytest.mark.asyncio
async def test_a_current_version_gets_no_lifecycle_headers(monkeypatch):
    _patch_settings(monkeypatch, _settings())
    resp = _Resp()
    await av.public_api_lifecycle(_Req("/api/public/v1/kpis"), resp)
    assert resp.headers == {}


@pytest.mark.asyncio
async def test_a_deprecated_version_still_serves_but_announces(monkeypatch):
    """Deprecated means 'still works, start moving' — a 200 with headers, not an error."""
    s = _settings(public_api_v1_deprecated_on=date(2020, 1, 31),
                  public_api_v1_sunset_on=date(2099, 7, 31))
    _patch_settings(monkeypatch, s)

    resp = _Resp()
    await av.public_api_lifecycle(_Req("/api/public/v1/kpis"), resp)   # does not raise
    assert resp.headers["Deprecation"] == "Fri, 31 Jan 2020 00:00:00 GMT"
    assert resp.headers["Sunset"] == "Fri, 31 Jul 2099 00:00:00 GMT"
    assert 'rel="deprecation"' in resp.headers["Link"]
    assert s.public_api_policy_url in resp.headers["Link"]


@pytest.mark.asyncio
async def test_a_sunset_version_stops_answering(monkeypatch):
    """The date was a promise. Serving past it would make the next one a bluff."""
    s = _settings(public_api_v1_deprecated_on=date(2020, 1, 31),
                  public_api_v1_sunset_on=date(2020, 7, 31))
    _patch_settings(monkeypatch, s)

    with pytest.raises(HTTPException) as ei:
        await av.public_api_lifecycle(_Req("/api/public/v1/kpis"), _Resp())

    assert ei.value.status_code == 410
    detail = ei.value.detail
    assert detail["error"] == "api_version_sunset"
    assert detail["sunset_on"] == "2020-07-31"
    assert "v1" not in detail["supported_versions"]     # it is gone, and says so
    assert detail["policy"] == s.public_api_policy_url


@pytest.mark.asyncio
async def test_the_410_carries_the_same_headers_a_client_was_already_reading(monkeypatch):
    """A machine client polling `Sunset` should not have to special-case the day
    the version actually goes away."""
    s = _settings(public_api_v1_deprecated_on=date(2020, 1, 31),
                  public_api_v1_sunset_on=date(2020, 7, 31))
    _patch_settings(monkeypatch, s)

    with pytest.raises(HTTPException) as ei:
        await av.public_api_lifecycle(_Req("/api/public/v1/kpis"), _Resp())

    h = ei.value.headers
    assert h["Sunset"] == "Fri, 31 Jul 2020 00:00:00 GMT"
    assert h["Deprecation"] == "Fri, 31 Jan 2020 00:00:00 GMT"
    assert 'rel="deprecation"' in h["Link"]


@pytest.mark.asyncio
async def test_discovery_survives_the_sunset_of_every_version(monkeypatch):
    """The one endpoint an integrator hits after a 410 must not itself 410."""
    s = _settings(public_api_v1_deprecated_on=date(2020, 1, 31),
                  public_api_v1_sunset_on=date(2020, 7, 31))
    _patch_settings(monkeypatch, s)

    resp = _Resp()
    await av.public_api_lifecycle(_Req("/api/public/versions"), resp)  # must not raise
    assert resp.headers == {}


# --------------------------------------------------------------------------
# 4. End-to-end through the real router.
#
# The unit tests above call the dependency directly, so they would still pass if
# it were never attached to the router, or if FastAPI dropped the headers it
# sets. These drive a real request through the real public router.
# --------------------------------------------------------------------------

def _real_client(monkeypatch, **lifecycle_kw):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services.database import get_db
    import app.routes.kpis as kpis_mod

    _patch_settings(monkeypatch, _settings(**lifecycle_kw))

    async def _fake_kpis(db, *a, **k):
        return {"total_units": 1}

    monkeypatch.setattr(kpis_mod, "compute_and_cache_kpis", _fake_kpis)
    monkeypatch.setattr(kpis_mod, "_serialize_kpi_dates", lambda d: d)

    app = FastAPI()
    app.include_router(public_api.router, prefix="/api/public")
    app.dependency_overrides[public_api.get_api_context] = lambda: {"tenant_id": 1, "scopes": ["*"]}
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_e2e_current_version_serves_clean(monkeypatch):
    r = _real_client(monkeypatch).get("/api/public/v1/kpis")
    assert r.status_code == 200
    assert "deprecation" not in r.headers
    assert "sunset" not in r.headers


def test_e2e_deprecated_version_serves_200_with_headers(monkeypatch):
    """The dependency IS attached to the router, and FastAPI really does merge
    the headers it set into a successful response."""
    c = _real_client(monkeypatch,
                     public_api_v1_deprecated_on=date(2020, 1, 31),
                     public_api_v1_sunset_on=date(2099, 7, 31))
    r = c.get("/api/public/v1/kpis")
    assert r.status_code == 200
    assert r.headers["deprecation"] == "Fri, 31 Jan 2020 00:00:00 GMT"
    assert r.headers["sunset"] == "Fri, 31 Jul 2099 00:00:00 GMT"
    assert 'rel="deprecation"' in r.headers["link"]


def test_e2e_sunset_version_410s_before_auth_even_runs(monkeypatch):
    """The lifecycle gate is a router-level dependency, so a retired version stops
    answering regardless of whether the caller's key is valid."""
    c = _real_client(monkeypatch,
                     public_api_v1_deprecated_on=date(2020, 1, 31),
                     public_api_v1_sunset_on=date(2020, 7, 31))
    r = c.get("/api/public/v1/kpis")
    assert r.status_code == 410
    assert r.json()["detail"]["error"] == "api_version_sunset"
    assert r.headers["sunset"] == "Fri, 31 Jul 2020 00:00:00 GMT"


def test_e2e_discovery_still_answers_after_sunset(monkeypatch):
    c = _real_client(monkeypatch,
                     public_api_v1_deprecated_on=date(2020, 1, 31),
                     public_api_v1_sunset_on=date(2020, 7, 31))
    r = c.get("/api/public/versions")
    assert r.status_code == 200
    assert r.json()["supported"][0]["status"] == "sunset"


# --------------------------------------------------------------------------
# 5. Config refuses to express a broken promise.
# --------------------------------------------------------------------------

def test_a_sunset_without_a_deprecation_is_rejected():
    with pytest.raises(ValueError, match="announced as deprecated"):
        _settings(public_api_v1_sunset_on=date(2027, 7, 31))


def test_a_sunset_on_or_before_the_deprecation_is_rejected():
    with pytest.raises(ValueError, match="strictly after"):
        _settings(public_api_v1_deprecated_on=date(2027, 7, 31),
                  public_api_v1_sunset_on=date(2027, 7, 31))
    with pytest.raises(ValueError, match="strictly after"):
        _settings(public_api_v1_deprecated_on=date(2027, 7, 31),
                  public_api_v1_sunset_on=date(2027, 1, 1))


def test_an_announced_deprecation_alone_is_valid():
    """Deprecate now, decide the retirement date later — the common real path."""
    s = _settings(public_api_v1_deprecated_on=date(2027, 1, 31))
    assert s.public_api_v1_sunset_on is None
