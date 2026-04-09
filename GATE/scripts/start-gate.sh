#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="$(uname -m)"

echo "[ZeroCloud] Starting MAGI backend on ${ARCH}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

cd "${ROOT_DIR}/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --quiet --disable-pip-version-check -r requirements.txt

export PYTHONPATH="${PYTHONPATH:-}:."
exec python3 -m app.main
