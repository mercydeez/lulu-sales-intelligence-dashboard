#!/usr/bin/env bash
# =============================================================================
# gen-self-signed-ssl.sh — generate a SELF-SIGNED TLS pair for nginx.
#
# Usage (from the repo root):
#   bash scripts/gen-self-signed-ssl.sh [hostname]     # default: localhost
#
# Writes nginx/ssl/cert.pem + nginx/ssl/key.pem, which is exactly where
# docker-compose.production.yml mounts them (/etc/nginx/ssl in the nginx
# container). The directory is gitignored — certs and keys are never committed.
#
# STAGING / SMOKE-TEST ONLY. See the warning printed at the end.
# =============================================================================
set -euo pipefail

CN="${1:-localhost}"
SSL_DIR="nginx/ssl"

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl not found on PATH" >&2
  exit 1
fi

mkdir -p "$SSL_DIR"

openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout "$SSL_DIR/key.pem" \
  -out "$SSL_DIR/cert.pem" \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=DNS:${CN}"

chmod 600 "$SSL_DIR/key.pem"

echo ""
echo "Wrote $SSL_DIR/cert.pem and $SSL_DIR/key.pem (CN=${CN}, valid 365 days)."
echo ""
echo "WARNING: this certificate is SELF-SIGNED — for staging and smoke tests ONLY."
echo "         Browsers will show a security warning and refuse silent connections."
echo "         Production MUST use a CA-issued certificate via the certbot webroot"
echo "         flow documented in docs/runbooks/TLS_CERTS.md (nothing automates"
echo "         certbot for you — issuance and renewal are operator actions)."
