#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  printf '.env is required before live-provider workflows. Run make env.\n' >&2
  exit 1
fi

printf 'Live provider mode is intentionally gated.\n'
printf 'Complete IBKR adapter wiring, paper trading validation, and operator runbook review before enabling this path.\n'
read -r -p "Acknowledge and continue with LEAN live command scaffolding? [y/N]: " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  printf 'Live provider workflow aborted by operator.\n'
  exit 0
fi

if ! command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI is not installed. Run make setup first.\n' >&2
  exit 1
fi

"$PROJECT_ROOT/scripts/sync_lean_config.sh"

cd "$PROJECT_ROOT/lean_workspace"
lean live "QualityGrowthPi"
