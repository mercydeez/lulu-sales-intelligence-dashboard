#!/bin/sh
# =============================================================================
# smoke-deploy.sh (E0-3) — gate a deploy on real health.
# Hits /health/live, /health/ready, /health/deep at $BASE_URL, fails on non-2xx,
# and asserts /health/deep covers DB/Redis/migrations/worker-heartbeat with a
# fresh (non-missing) worker and no leaked secrets. python3 only (no jq).
# Usable locally and in GitHub Actions; needs no credentials.
# =============================================================================
set -eu

BASE_URL="${BASE_URL:-}"
if [ -z "$BASE_URL" ]; then
  echo "ERROR: BASE_URL is required (e.g. BASE_URL=https://api.example.com $0)"; exit 2
fi
BASE_URL="${BASE_URL%/}"

# --- 2xx checks on the liveness/readiness probes ---------------------------
check_2xx() {
  path="$1"
  code="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}${path}" || echo 000)"
  echo "  ${path} -> HTTP ${code}"
  case "$code" in
    2*) return 0 ;;
    *) echo "ERROR: ${path} returned ${code} (expected 2xx)"; return 1 ;;
  esac
}

echo "→ smoke: liveness / readiness"
check_2xx /health/live
check_2xx /health/ready

# --- /health/deep body assertions ------------------------------------------
echo "→ smoke: /health/deep body"
DEEP="$(curl -fsS "${BASE_URL}/health/deep")" || { echo "ERROR: /health/deep not 2xx"; exit 1; }

SMOKE_DEEP="$DEEP" python3 <<'PY'
import os, sys, json
raw = os.environ["SMOKE_DEEP"]

# Never let obvious secrets appear in the health payload.
low = raw.lower()
for needle in ("alert_webhook_url", "postgres://", "redis://", "jwt_secret", "secret_key", "password"):
    if needle in low:
        print(f"ERROR: possible secret '{needle}' present in /health/deep response"); sys.exit(1)

try:
    body = json.loads(raw)
except Exception as e:
    print(f"ERROR: /health/deep is not JSON: {e}"); sys.exit(1)

checks = body.get("checks", {})
for name in ("database", "redis", "migrations", "worker_heartbeat"):
    if name not in checks:
        print(f"ERROR: /health/deep missing check '{name}'"); sys.exit(1)

def status_of(v):
    return v.get("status") if isinstance(v, dict) else v

wh = status_of(checks.get("worker_heartbeat"))
if wh == "missing":
    print("ERROR: worker heartbeat is 'missing' — worker not reporting in production smoke"); sys.exit(1)

print(f"  overall status: {body.get('status')}")
print(f"  database={status_of(checks.get('database'))} redis={status_of(checks.get('redis'))} "
      f"migrations={status_of(checks.get('migrations'))} worker_heartbeat={wh}")
print("  ✅ /health/deep checks present; no leaked secrets; worker heartbeat not missing")
PY

echo "✅ smoke-deploy passed for ${BASE_URL}"
