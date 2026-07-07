#!/bin/sh
# =============================================================================
# deploy-compose.sh (E0-3) — trigger a deploy in one of two modes.
#
# Mode 1 (webhook): POST a deploy payload to DEPLOY_WEBHOOK_URL (e.g. a PaaS
#   deploy hook, or your own runner). Set DEPLOY_WEBHOOK_URL.
# Mode 2 (ssh):     SSH to the host and run docker compose up on the given ref.
#   Set DEPLOY_SSH_HOST + DEPLOY_SSH_USER + DEPLOY_SSH_KEY + DEPLOY_APP_DIR.
#
# DRY_RUN=true validates configuration/branching WITHOUT deploying (used by CI to
# syntax/flow-check the script without secrets). Secrets are never printed.
# POSIX sh.
# =============================================================================
set -eu

DEPLOY_ENVIRONMENT="${DEPLOY_ENVIRONMENT:-unknown}"
DEPLOY_REF="${DEPLOY_REF:-}"
DEPLOY_SHA="${DEPLOY_SHA:-}"
DEPLOY_REPOSITORY="${DEPLOY_REPOSITORY:-${GITHUB_REPOSITORY:-unknown}}"
DEPLOY_COMPOSE_FILE="${DEPLOY_COMPOSE_FILE:-docker-compose.production.yml}"
DRY_RUN="${DRY_RUN:-false}"

# A timestamp without depending on GNU date flags.
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo 'unknown')"

log() { echo "[deploy] $*"; }

deploy_webhook() {
  log "mode=webhook environment=${DEPLOY_ENVIRONMENT} ref=${DEPLOY_REF:-HEAD} sha=${DEPLOY_SHA:-unknown}"
  payload=$(printf '{"ref":"%s","sha":"%s","environment":"%s","repository":"%s","timestamp":"%s"}' \
    "${DEPLOY_REF}" "${DEPLOY_SHA}" "${DEPLOY_ENVIRONMENT}" "${DEPLOY_REPOSITORY}" "${NOW}")
  if [ "$DRY_RUN" = "true" ]; then
    log "DRY_RUN: would POST payload to the configured webhook (URL hidden)"
    log "DRY_RUN: payload=${payload}"
    return 0
  fi
  # -f fails on HTTP >=400; URL never echoed.
  if curl -fsS -X POST -H "Content-Type: application/json" -d "${payload}" "${DEPLOY_WEBHOOK_URL}" >/dev/null; then
    log "webhook deploy triggered"
  else
    log "ERROR: webhook deploy failed"; return 1
  fi
}

deploy_ssh() {
  log "mode=ssh environment=${DEPLOY_ENVIRONMENT} host=${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST} ref=${DEPLOY_REF:-HEAD}"
  if [ -z "${DEPLOY_REF}" ]; then
    log "ERROR: DEPLOY_REF is required for ssh deploy"; return 1
  fi
  remote_script=$(cat <<EOF
set -eu
cd "${DEPLOY_APP_DIR}"
git fetch --all --tags
git checkout "${DEPLOY_REF}"
docker compose -f "${DEPLOY_COMPOSE_FILE}" --env-file .env.production pull || true
docker compose -f "${DEPLOY_COMPOSE_FILE}" --env-file .env.production up -d --build
docker compose -f "${DEPLOY_COMPOSE_FILE}" --env-file .env.production ps
EOF
)
  if [ "$DRY_RUN" = "true" ]; then
    log "DRY_RUN: would SSH and run (key hidden):"
    printf '%s\n' "$remote_script" | sed 's/^/[deploy][remote] /'
    return 0
  fi
  keyfile="$(mktemp)"
  # Ensure the temp key is always removed.
  trap 'rm -f "$keyfile"' EXIT INT TERM
  umask 177
  printf '%s\n' "${DEPLOY_SSH_KEY}" > "$keyfile"
  chmod 600 "$keyfile"
  ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -i "$keyfile" \
      "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}" "$remote_script"
  rm -f "$keyfile"
  trap - EXIT INT TERM
  log "ssh deploy completed"
}

# --- Mode selection ---------------------------------------------------------
if [ -n "${DEPLOY_WEBHOOK_URL:-}" ]; then
  deploy_webhook
elif [ -n "${DEPLOY_SSH_HOST:-}" ] && [ -n "${DEPLOY_SSH_USER:-}" ] \
     && [ -n "${DEPLOY_SSH_KEY:-}" ] && [ -n "${DEPLOY_APP_DIR:-}" ]; then
  deploy_ssh
elif [ "$DRY_RUN" = "true" ]; then
  log "DRY_RUN: no deploy mode configured (neither webhook nor ssh) — this is OK for CI validation"
  exit 0
else
  log "ERROR: no deploy mode configured. Set DEPLOY_WEBHOOK_URL (webhook mode) OR"
  log "       DEPLOY_SSH_HOST/USER/KEY/APP_DIR (ssh mode)."
  exit 1
fi
