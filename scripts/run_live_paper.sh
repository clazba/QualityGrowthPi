#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  printf '.env is required before paper trading. Run make env.\n' >&2
  exit 1
fi

read -r -p "Start paper trading mode for QualityGrowthPi? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Paper trading aborted by operator.\n'
  exit 0
fi

cd "$PROJECT_ROOT/lean_workspace"
lean live "QualityGrowthPi"
