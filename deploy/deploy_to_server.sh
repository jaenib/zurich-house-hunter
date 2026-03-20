#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEPLOY_HOST="${DEPLOY_HOST:-82.165.45.100}"
DEPLOY_USER="${DEPLOY_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/usr/bots/zurich-house-hunter}"
SERVICE_NAME="${SERVICE_NAME:-zurich-house-hunter.service}"
SSH_DEST="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_OPTS=(-o StrictHostKeyChecking=no)

if [[ ! -f "${PROJECT_ROOT}/config.json" ]]; then
  echo "config.json is missing in ${PROJECT_ROOT}" >&2
  exit 1
fi

echo "Deploying ${PROJECT_ROOT} to ${SSH_DEST}:${REMOTE_DIR}"

ssh "${SSH_OPTS[@]}" "${SSH_DEST}" "mkdir -p '${REMOTE_DIR}' '${REMOTE_DIR}/data'"

rsync -az --delete \
  -e "ssh -o StrictHostKeyChecking=no" \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "__pycache__/" \
  --exclude "*.py[cod]" \
  --exclude ".DS_Store" \
  --exclude ".pytest_cache/" \
  --exclude "build/" \
  --exclude "dist/" \
  --exclude "data/" \
  --exclude "tests/" \
  "${PROJECT_ROOT}/" "${SSH_DEST}:${REMOTE_DIR}/"

ssh "${SSH_OPTS[@]}" "${SSH_DEST}" "
  set -euo pipefail
  cd '${REMOTE_DIR}'
  if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
  fi
  install -m 644 deploy/zurich-house-hunter.service /etc/systemd/system/${SERVICE_NAME}
  systemctl daemon-reload
  systemctl enable --now ${SERVICE_NAME}
  systemctl restart ${SERVICE_NAME}
  systemctl status ${SERVICE_NAME} --no-pager
"
