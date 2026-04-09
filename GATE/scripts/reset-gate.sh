#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[ZeroCloud] Resetting this GATE configuration..."

rm -f \
  "${ROOT_DIR}/backend/data/profile.json" \
  "${ROOT_DIR}/backend/data/kits.json" \
  "${ROOT_DIR}/backend/data/events.json"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  if grep -q '^ZC_PROFILE_CONFIGURED=' "${ROOT_DIR}/.env"; then
    sed -i 's/^ZC_PROFILE_CONFIGURED=.*/ZC_PROFILE_CONFIGURED="0"/' "${ROOT_DIR}/.env"
  else
    printf '\nZC_PROFILE_CONFIGURED="0"\n' >> "${ROOT_DIR}/.env"
  fi
fi

echo "[ZeroCloud] Done. Next start will enter first-time setup flow."
