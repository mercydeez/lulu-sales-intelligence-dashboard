"""
E0-3/E0-4 — deploy pipeline + production compose guards. Pure file-reading
assertions; no Docker, no network. Runs in the normal backend CI job.
"""
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def _exists(rel: str) -> bool:
    return os.path.exists(os.path.join(_ROOT, rel))


def _strip_comments(text: str, marker: str) -> str:
    """Drop full-line comments so a helpful comment mentioning a demo artifact
    (e.g. 'train.csv is intentionally not mounted') doesn't read as an actual
    mount. Matches how `docker compose config` renders (comments removed)."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(marker))


PROD_COMPOSE = "docker-compose.production.yml"


# --- E0-4: production compose is demo-free -------------------------------------
def test_prod_compose_has_no_demo_or_seed_mounts():
    # Check the CONFIG (comments stripped) — comments may still document the intent.
    text = _strip_comments(_read(PROD_COMPOSE), "#")
    for forbidden in ("train.csv", "seed_data.sql", "/data/train.csv"):
        assert forbidden not in text, f"production compose must not mount '{forbidden}'"


def test_prod_compose_uses_schema_only_prod_init():
    text = _read(PROD_COMPOSE)
    assert "prod-init.sql" in text, "production Postgres should bootstrap from prod-init.sql"
    assert _exists("database/prod-init.sql")


def test_prod_init_has_no_demo_data():
    # Strip SQL comments so the "no demo data" explanations don't trip the check.
    text = _strip_comments(_read("database/prod-init.sql"), "--").lower()
    for forbidden in ("retaildemo.app", "train.csv", "insert into users", "insert into stores", "insert into items"):
        assert forbidden not in text, f"prod-init.sql must not seed demo data ('{forbidden}')"


def test_prod_compose_core_services_and_healthcheck():
    text = _read(PROD_COMPOSE)
    assert "/health/ready" in text, "backend healthcheck should target /health/ready"
    # `singletons` is now load-bearing: it hosts every continuous background loop
    # (generator/reset/warmer/trainer/partition-maintenance) so the API workers run
    # none — guard its presence.
    for svc in ("worker:", "migrate:", "backup:", "singletons:"):
        assert svc in text, f"production compose should define the {svc} service"


def test_prod_compose_keeps_e0_2_env_wiring():
    text = _read(PROD_COMPOSE)
    for key in ("ALERT_ENABLED", "ALERT_WEBHOOK_URL",
                "WORKER_HEARTBEAT_INTERVAL_MS", "WORKER_HEARTBEAT_STALE_SECONDS"):
        assert key in text, f"production compose lost E0-2 env wiring: {key}"


def test_prod_compose_no_startup_seed_or_generator():
    """The API/backend must never seed on startup or force synthetic generation on.

    The continuous singletons (including the generator) now live in the dedicated
    `singletons` service, and the generator self-gates on DEMO_MODE +
    LIVE_GENERATOR_ENABLED. Both flags default to false and are NOT hardcoded true
    anywhere, so a non-demo production deploy runs the maintenance loops and
    generates nothing. (A demo deploy opts in by setting the two env vars.)
    """
    text = _strip_comments(_read(PROD_COMPOSE), "#")
    assert 'RUN_SEED_ON_STARTUP: "true"' not in text
    # No service hardcodes the generator / demo mode ON — both are env-gated,
    # default false. This is a STRONGER guarantee than the old demo-profile check:
    # generation is off unless explicitly enabled, not merely quarantined.
    assert 'LIVE_GENERATOR_ENABLED: "true"' not in text, \
        "the live generator must be env-gated (default false), never hardcoded on"
    assert 'DEMO_MODE: "true"' not in text, \
        "demo mode must be env-gated (default false), never hardcoded on"
    # The singletons service is the ONLY host that can run the generator, and it
    # gates it on the (default-false) env vars.
    assert "singletons:" in text
    assert "LIVE_GENERATOR_ENABLED: ${LIVE_GENERATOR_ENABLED:-false}" in text


# --- E0-3: pipeline artifacts exist -------------------------------------------
def test_deploy_workflow_exists():
    assert _exists(".github/workflows/deploy.yml")
    wf = _read(".github/workflows/deploy.yml")
    assert "deploy-staging" in wf and "deploy-production" in wf
    assert "permissions:" in wf and "contents: read" in wf


def test_deploy_scripts_exist():
    for s in ("scripts/validate-production-compose.sh",
              "scripts/smoke-deploy.sh",
              "scripts/deploy-compose.sh"):
        assert _exists(s), f"missing deploy script: {s}"


def test_deploy_runbook_exists():
    assert _exists("docs/runbooks/DEPLOY_PIPELINE.md")
    assert _exists("docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md")
