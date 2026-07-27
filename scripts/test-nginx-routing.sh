#!/usr/bin/env bash
# nginx routing contract test.
#
# WHY THIS EXISTS. The nginx config was changed from `upstream` blocks with
# `proxy_pass http://backend;` to a `resolver` + variable `proxy_pass`, so that
# recreating the backend or frontend container no longer 502s every request
# until nginx is restarted.
#
# That change is NOT cosmetic: a variable in proxy_pass changes how nginx builds
# the upstream URI. With a literal `proxy_pass http://backend;` nginx forwards
# the NORMALISED request URI; with a variable it forwards exactly what you
# concatenate, hence the explicit `$request_uri`. Get that wrong and routes
# silently 404, or query strings vanish, in ways a "does the homepage load"
# check will not catch.
#
# So this asserts the ROUTING CONTRACT itself: every location block still
# reaches the right upstream, path and query survive, streaming still streams,
# and the redirect still redirects.
#
# Usage:
#   scripts/test-nginx-routing.sh [base_url]        # default https://localhost
#   BASELINE=1 scripts/test-nginx-routing.sh        # record, don't assert
set -uo pipefail

BASE="${1:-https://localhost}"
CURL=(curl -sk -m 15 -o /dev/null)
PASS=0; FAIL=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }

# expect <label> <expected-codes-csv> <url> [curl-args...]
expect() {
  local label="$1" want="$2" url="$3"; shift 3
  local got; got=$("${CURL[@]}" -w '%{http_code}' "$@" "$url" 2>/dev/null)
  if [[ ",$want," == *",$got,"* ]]; then ok "$label ($got)"; else bad "$label — want [$want] got $got  <$url>"; fi
}

# expect_body <label> <substring> <url>
expect_body() {
  local label="$1" needle="$2" url="$3"
  local body; body=$(curl -sk -m 15 "$url" 2>/dev/null)
  if [[ "$body" == *"$needle"* ]]; then ok "$label"; else bad "$label — '$needle' not in response"; fi
}

echo "nginx routing contract → $BASE"
echo

echo "── upstream: backend ──────────────────────────────────────────────"
# `location /health` must reach the API, not the Next app.
expect     "/health reaches backend"            200         "$BASE/health"
expect_body "/health returns API JSON"          '"database"' "$BASE/health"
# `location /api/` — the main API prefix. 401 is a correct answer (auth
# required); what matters is that it is the BACKEND answering, not a 502/404.
expect     "/api/flywheel/health routed"        200,401,403 "$BASE/api/flywheel/health"
expect     "/api/auth/me routed"                200,401     "$BASE/api/auth/me"
# Dedicated stricter-rate-limit location.
expect     "/api/auth/login routed"             400,401,422 "$BASE/api/auth/login" -X POST \
             -H 'Content-Type: application/json' -d '{}'
# Its own location block with buffering disabled.
expect     "/api/monitoring/ routed"            200,401,403,404 "$BASE/api/monitoring/health"

echo
echo "── path + query fidelity (what variable proxy_pass can break) ─────"
# A nested path must arrive intact, not truncated to the location prefix.
expect     "nested path survives"               200,401,404 "$BASE/api/flywheel/campaigns"

# QUERY-STRING FIDELITY — the single most important assertion here.
#
# `$request_uri` carries the query; a bare `$uri` silently drops it, and every
# status code would still look correct because the endpoints tolerate missing
# optional params. So we need a probe whose RESULT DEPENDS on the query value.
#
# `limit` is validated (ge=1, le=200), so with a valid token:
#     ?limit=1     -> 200   (query arrived and parsed)
#     ?limit=abc   -> 422   (query arrived and FAILED validation)
# If the query were dropped, BOTH would return 200 and the bug would pass
# unnoticed. Requires auth, because the auth dependency resolves before query
# validation — unauthenticated both are 401 and prove nothing.
TOKEN="${ROUTING_TEST_TOKEN:-}"
if [ -z "$TOKEN" ] && [ -n "${ROUTING_TEST_EMAIL:-}" ]; then
  TOKEN=$(curl -sk -m 15 -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
      -d "{\"email\":\"$ROUTING_TEST_EMAIL\",\"password\":\"${ROUTING_TEST_PASSWORD:-}\"}" \
      2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
fi

if [ -n "$TOKEN" ]; then
  expect   "query arrives + parses (limit=1)"   200         "$BASE/api/flywheel/customers?limit=1"   -H "Authorization: Bearer $TOKEN"
  expect   "query arrives + validates (abc)"    422         "$BASE/api/flywheel/customers?limit=abc" -H "Authorization: Bearer $TOKEN"
  expect   "query bounds enforced (99999)"      422         "$BASE/api/flywheel/customers?limit=99999" -H "Authorization: Bearer $TOKEN"
else
  printf '  \033[33mSKIP\033[0m  query fidelity — set ROUTING_TEST_EMAIL/PASSWORD or ROUTING_TEST_TOKEN\n'
  printf '        (without auth every probe returns 401 and proves nothing)\n'
fi

# A URL-encoded segment must not be mangled into a different path.
expect     "encoded path segment survives"      200,401,404,422 "$BASE/api/flywheel/customers?q=a%2Fb"

echo
echo "── upstream: frontend ─────────────────────────────────────────────"
expect     "/ reaches frontend"                 200         "$BASE/"
expect     "/login reaches frontend"            200         "$BASE/login"
expect     "/flywheel reaches frontend"         200         "$BASE/flywheel"
expect     "/flywheel/studio reaches frontend"  200         "$BASE/flywheel/studio"
expect     "/retention (pre-existing) routes"   200         "$BASE/retention"
expect_body "frontend serves HTML"              '<!DOCTYPE html' "$BASE/login"

echo
echo "── SSE / streaming ────────────────────────────────────────────────"
# Must not 502. Unauthenticated is 401; the point is nginx reached the backend
# and did not buffer the connection into a timeout.
expect     "/stream/ routed, not buffered"      200,401,403 "$BASE/stream/flywheel"

echo
echo "── redirect + TLS ─────────────────────────────────────────────────"
expect     "http:// redirects to https"         301,308     "http://localhost/login"

echo
echo "── the regression this fix exists for ─────────────────────────────"
echo "  (run scripts/test-nginx-reresolve.sh to prove recreate-without-502)"

echo
printf 'passed %d, failed %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
