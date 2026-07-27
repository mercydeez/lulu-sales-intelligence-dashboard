#!/usr/bin/env bash
# Proves nginx survives an upstream container being RECREATED.
#
# THE BUG THIS EXISTS FOR. With plain `upstream { server backend:8000; }` blocks,
# OSS nginx resolves the name ONCE at startup and caches the IP forever. Docker
# gives a recreated container a NEW IP, so nginx keeps proxying to an address
# nothing is listening on — every request 502s until someone restarts nginx.
#
# That is a silent, total outage on every backend redeploy, and it is invisible
# to a normal smoke test because the stack looks healthy: all containers up, the
# API reachable directly, only nginx wrong.
#
# This test recreates the backend and asserts traffic recovers WITHOUT touching
# nginx. Run it against the old config and it fails; against the resolver config
# it passes. That is the whole point.
#
# Usage: scripts/test-nginx-reresolve.sh [project] [compose-file] [base_url]
set -uo pipefail

PROJECT="${1:-lulu-prod}"
COMPOSE="${2:-docker-compose.production.yml}"
BASE="${3:-https://localhost}"
ENVFILE="${ENVFILE:-.env.production}"
DC=(docker compose -p "$PROJECT" --env-file "$ENVFILE" -f "$COMPOSE")

probe() { curl -sk -m 10 -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null; }

echo "nginx upstream re-resolution test"
echo

before=$(probe)
echo "  before recreate            : $before"
if [ "$before" != "200" ]; then
  echo "  ABORT — stack is not healthy to begin with; fix that first."
  exit 1
fi

old_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
           "$(docker ps -qf name=backend --filter "label=com.docker.compose.project=$PROJECT" | head -1)" 2>/dev/null)
echo "  backend IP before          : ${old_ip:-unknown}"

# FORCE THE IP TO ACTUALLY CHANGE. Simply recreating usually hands the same
# address straight back, and then the test proves nothing while looking green.
# So: stop the backend, park a throwaway container on the network to consume the
# freed address, bring the backend back on a NEW ip, then release the squatter.
NET=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' \
        "$(docker ps -qf name=backend --filter "label=com.docker.compose.project=$PROJECT" | head -1)" 2>/dev/null)
echo "  network                    : ${NET:-unknown}"

echo "  stopping backend…"
"${DC[@]}" stop backend >/dev/null 2>&1

# Park SEVERAL squatters. One is not enough: Docker often hands the freed
# address straight back to the recreated container, and the run then proves
# nothing. A small block of them guarantees the backend lands somewhere new.
SQUATTERS=()
if [ -n "$NET" ]; then
  for _ in 1 2 3 4; do
    id=$(docker run -d --rm --network "$NET" alpine sleep 180 2>/dev/null || true)
    [ -n "$id" ] && SQUATTERS+=("$id")
  done
  echo "  parked ${#SQUATTERS[@]} squatter(s) to consume the freed addresses"
fi

echo "  recreating backend (NOT touching nginx)…"
"${DC[@]}" up -d --force-recreate --no-deps backend >/dev/null 2>&1

# Wait for the backend itself to be serving again, so we are testing nginx's
# resolution and not merely racing container startup.
for _ in $(seq 1 60); do
  s=$(docker inspect -f '{{.State.Health.Status}}' \
        "$(docker ps -qf name=backend --filter "label=com.docker.compose.project=$PROJECT" | head -1)" 2>/dev/null)
  [ "$s" = "healthy" ] && break
  sleep 5
done

new_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
           "$(docker ps -qf name=backend --filter "label=com.docker.compose.project=$PROJECT" | head -1)" 2>/dev/null)
echo "  backend IP after           : ${new_ip:-unknown}"

[ ${#SQUATTERS[@]} -gt 0 ] && docker rm -f "${SQUATTERS[@]}" >/dev/null 2>&1

# A run where the address never moved cannot distinguish a fixed nginx from a
# broken one. Report INCONCLUSIVE rather than PASS — a green that proves nothing
# is worse than a red, because it retires the very check that would have caught
# the regression.
if [ -n "$old_ip" ] && [ "$old_ip" = "$new_ip" ]; then
  echo
  echo "  INCONCLUSIVE — the backend kept the same IP ($old_ip), so nginx was"
  echo "  never asked to re-resolve. This run neither proves nor disproves the"
  echo "  fix. Re-run; if it keeps happening the squatter trick is not working."
  exit 2
fi

# Allow the resolver's TTL to lapse (valid=10s) before judging.
echo "  waiting out the resolver TTL…"
after=""
for _ in $(seq 1 12); do
  sleep 5
  after=$(probe)
  [ "$after" = "200" ] && break
done

echo "  after recreate             : $after"
echo

if [ "$after" = "200" ]; then
  echo "  PASS — nginx re-resolved the upstream on its own. No restart needed."
  exit 0
fi
echo "  FAIL — still $after after recreate. nginx is holding a stale upstream IP;"
echo "         traffic only recovers with 'docker compose restart nginx'."
exit 1
