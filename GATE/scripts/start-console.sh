#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="$(uname -m)"

echo "[ZeroCloud] Starting Vue console on ${ARCH}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

cd "${ROOT_DIR}/frontend"
npm install --no-audit --no-fund
exec npm run dev -- --host 0.0.0.0 --port "${VITE_PORT:-5173}"
