#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "help" || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage: ./scripts/clear-local-state.sh [help]

Removes local Orchestra runtime state for this checkout:
  state/orchestra.db
  state/orchestra.db-*
  logs/*.jsonl
  state/return-artifacts/*
  state/requests/*

Does not remove Pi/Hermes/OpenCode session history.
EOF
  exit 0
fi

cd "$(dirname "$0")/.."

rm -f state/orchestra.db state/orchestra.db-*
rm -f logs/*.jsonl
rm -f state/return-artifacts/*
rm -f state/requests/*
mkdir -p state/return-artifacts state/requests logs
