"""Regression test for Critical finding C3 — production migration env wiring.

`services.role_password_sync.sync_role_passwords()` runs at the end of every
migration pass and, in production, ALTERs the non-owner DB roles (app_rw /
worker_rw / sage_ro) to the passwords that backend/worker/sage connect with.
It reads those passwords from ITS OWN process environment
(WORKER_DB_PASSWORD | WORKER_DATABASE_URL, RLS_DATABASE_URL, SAGE_DATABASE_URL).

The dedicated `migrate` service is where that sync runs in production. If its
compose `environment:` omits those variables, the roles keep the migration
default dev passwords and every backend-RLS / worker / sage connection fails
auth on a real deploy. This test pins the wiring so it cannot silently regress.
"""
import os

import pytest

yaml = pytest.importorskip("yaml")

_COMPOSE = os.path.join(
    os.path.dirname(__file__), "..", "..", "docker-compose.production.yml"
)

# The env vars sync_role_passwords() reads to align each non-owner role.
# worker_rw's secret may arrive as WORKER_DB_PASSWORD (plain) OR inside
# WORKER_DATABASE_URL; either satisfies the requirement for the migrate job.
_WORKER_SOURCES = ("WORKER_DB_PASSWORD", "WORKER_DATABASE_URL")
_APP_SOURCE = "RLS_DATABASE_URL"
_SAGE_SOURCE = "SAGE_DATABASE_URL"


def _migrate_env() -> dict:
    with open(_COMPOSE, encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    services = compose.get("services", {})
    assert "migrate" in services, "prod compose must define the one-shot migrate job"
    env = services["migrate"].get("environment", {})
    # compose `environment` can be a dict or a ["K=V", ...] list — normalize.
    if isinstance(env, list):
        env = dict(e.split("=", 1) if "=" in e else (e, "") for e in env)
    return env


def test_migrate_job_carries_role_password_sync_sources():
    env = _migrate_env()
    assert any(k in env for k in _WORKER_SOURCES), (
        "migrate job must receive WORKER_DB_PASSWORD (or WORKER_DATABASE_URL) so "
        "role-password-sync can align worker_rw; otherwise the worker fails auth in prod"
    )
    assert _APP_SOURCE in env, (
        "migrate job must receive RLS_DATABASE_URL so role-password-sync can align "
        "app_rw; otherwise the backend RLS connection fails auth in prod"
    )
    assert _SAGE_SOURCE in env, (
        "migrate job must receive SAGE_DATABASE_URL so role-password-sync can align "
        "sage_ro; otherwise the semantic-layer read role fails auth in prod"
    )


def test_migrate_role_secrets_match_the_backend_and_worker_values():
    """The migrate job must be handed the SAME interpolations the consuming
    services use, so the synced password is exactly what they connect with."""
    with open(_COMPOSE, encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    services = compose["services"]
    migrate_env = _migrate_env()
    backend_env = services["backend"].get("environment", {})
    worker_env = services["worker"].get("environment", {})

    # app_rw: migrate's RLS_DATABASE_URL interpolation must match the backend's.
    assert migrate_env.get(_APP_SOURCE) == backend_env.get(_APP_SOURCE), (
        "migrate and backend must interpolate RLS_DATABASE_URL identically"
    )
    # worker_rw: the worker builds WORKER_DATABASE_URL from ${WORKER_DB_PASSWORD};
    # migrate must see that same password variable.
    assert "WORKER_DB_PASSWORD" in migrate_env, "migrate must receive WORKER_DB_PASSWORD"
    assert "${WORKER_DB_PASSWORD" in worker_env.get("WORKER_DATABASE_URL", ""), (
        "worker's WORKER_DATABASE_URL should be built from ${WORKER_DB_PASSWORD}"
    )
