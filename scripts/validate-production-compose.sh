#!/bin/sh
# =============================================================================
# validate-production-compose.sh (E0-4 + D2)
# Guards docker-compose.production.yml against demo/seed artifacts and asserts the
# production topology (migrate/worker/backup, /health/ready healthcheck, E0-2 env,
# no auto-seed/generator). Also gates the two D2 deploy blockers: TLS material at
# nginx/ssl/{cert.pem,key.pem} (nginx cannot start without it) and a real public
# NEXT_PUBLIC_API_URL (baked into the browser bundle — internal hosts never work).
# Runs `docker compose config -q` when Docker is present; otherwise validates the
# raw compose source (render check skipped, warned). Uses python3 (no jq). POSIX sh.
# =============================================================================
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "ERROR: $COMPOSE_FILE not found (run from repo root)"; exit 1
fi

# --- Deploy blockers (D2): TLS material + public API origin -------------------
# nginx mounts ./nginx/ssl read-only and cannot START without cert.pem/key.pem.
for f in nginx/ssl/cert.pem nginx/ssl/key.pem; do
  if [ ! -f "$f" ]; then
    echo "ERROR: missing TLS material: $f — nginx cannot start without it."
    echo "       staging/smoke: bash scripts/gen-self-signed-ssl.sh <hostname>"
    echo "       production:    CA-issued cert via docs/runbooks/TLS_CERTS.md (certbot webroot)"
    exit 1
  fi
done

# NEXT_PUBLIC_API_URL is baked into the browser bundle at BUILD time; an internal
# hostname (backend:8000) or localhost is unreachable from any real browser.
if [ -z "${NEXT_PUBLIC_API_URL:-}" ]; then
  echo "ERROR: NEXT_PUBLIC_API_URL is not set."
  echo "       Set it to the public https origin the browser will call"
  echo "       (e.g. https://app.example.com) — it is baked into the frontend at build time."
  exit 1
fi
case "$NEXT_PUBLIC_API_URL" in
  *backend:8000*|*localhost*)
    echo "ERROR: NEXT_PUBLIC_API_URL='$NEXT_PUBLIC_API_URL' points at an internal/dev host."
    echo "       Browsers cannot resolve 'backend:8000' or reach 'localhost' on a deployed"
    echo "       host — use the public origin (e.g. https://app.example.com)."
    exit 1
    ;;
esac
export NEXT_PUBLIC_API_URL

# Safe dummy values so `docker compose config` can resolve required (:?) vars.
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ci-dummy-pg-pass}"
export REDIS_PASSWORD="${REDIS_PASSWORD:-ci-dummy-redis-pass}"
export WORKER_DB_PASSWORD="${WORKER_DB_PASSWORD:-ci-dummy-worker-pass}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-ci-test-secret-key-minimum-32-chars-long}"
export SECRET_KEY="${SECRET_KEY:-ci-test-app-secret-key-minimum-32-characters}"
export CORS_ORIGINS="${CORS_ORIGINS:-https://example.com}"

SRC="raw"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "→ docker present: validating rendered production compose"
  docker compose -f "$COMPOSE_FILE" config -q
  RENDERED="$(docker compose -f "$COMPOSE_FILE" config)"
  SRC="rendered"
else
  echo "WARN: Docker/Compose unavailable — validating RAW compose source (render check skipped)."
  echo "      CI runs the full rendered validation; static checks below still apply."
  RENDERED="$(cat "$COMPOSE_FILE")"
fi

COMPOSE_RENDERED="$RENDERED" COMPOSE_SRC="$SRC" python3 <<'PY'
import os, sys, yaml

src = os.environ["COMPOSE_SRC"]
text = os.environ["COMPOSE_RENDERED"]
data = yaml.safe_load(text)
services = (data or {}).get("services", {}) or {}
errors = []

# 1. Forbidden demo/seed artifacts anywhere in the config. Strip full-line
# comments first so a doc comment ("train.csv is intentionally not mounted") in
# raw mode isn't mistaken for a real mount (rendered config has no comments).
text_nc = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
for needle in ("train.csv", "/data/train.csv", "seed_data.sql", "seed_data"):
    if needle in text_nc:
        errors.append(f"forbidden production artifact present: '{needle}'")

# 2. Required services.
for svc in ("backend", "worker", "migrate", "backup", "postgres", "redis"):
    if svc not in services:
        errors.append(f"required service missing: '{svc}'")

def env_of(svc):
    e = (services.get(svc) or {}).get("environment", {})
    if isinstance(e, list):
        out = {}
        for item in e:
            if "=" in item:
                k, v = item.split("=", 1); out[k] = v
            else:
                out[item] = ""
        return out
    return e or {}

# 3. Backend healthcheck targets /health/ready.
be = services.get("backend", {}) or {}
hc = (be.get("healthcheck") or {}).get("test")
if not hc or "/health/ready" not in " ".join(hc if isinstance(hc, list) else [str(hc)]):
    errors.append("backend healthcheck does not target /health/ready")

# 4. Production must not auto-seed or run the live generator (backend service).
be_env = env_of("backend")
if str(be_env.get("RUN_SEED_ON_STARTUP", "")).lower() == "true":
    errors.append("backend RUN_SEED_ON_STARTUP=true (must be false in production)")
if str(be_env.get("LIVE_GENERATOR_ENABLED", "")).lower() == "true":
    errors.append("backend LIVE_GENERATOR_ENABLED=true (must be false/off outside demo profile)")

# 5. E0-2 monitoring/alerting env must remain wired.
for k in ("ALERT_ENABLED", "ALERT_WEBHOOK_URL"):
    if k not in be_env:
        errors.append(f"backend missing E0-2 env: {k}")
wk_env = env_of("worker")
for k in ("WORKER_HEARTBEAT_INTERVAL_MS", "WORKER_HEARTBEAT_STALE_SECONDS"):
    if k not in wk_env:
        errors.append(f"worker missing E0-2 heartbeat env: {k}")

if errors:
    print("❌ production compose validation FAILED (%s):" % src)
    for e in errors:
        print("   -", e)
    sys.exit(1)
print("✅ production compose validation passed (%s): no demo/seed artifacts; "
      "migrate/worker/backup present; /health/ready healthcheck; no auto-seed/"
      "generator; E0-2 env wired." % src)
PY

echo "validate-production-compose: OK"
