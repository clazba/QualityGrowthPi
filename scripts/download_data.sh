#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}"
LEAN_DATA_DIRECTORY="${LEAN_DATA_DIRECTORY:-$RUNTIME_ROOT/data/lean}"

mkdir -p "$LEAN_DATA_DIRECTORY" "$RUNTIME_ROOT/data/news_cache" "$RUNTIME_ROOT/data/market_cache"

printf 'Prepared local data directories under %s\n' "$RUNTIME_ROOT/data"
printf 'LEAN data directory: %s\n' "$LEAN_DATA_DIRECTORY"

if command -v lean >/dev/null 2>&1; then
  printf 'LEAN CLI detected. Data download remains operator-driven because dataset entitlements vary.\n'
  printf 'Use your licensed LEAN data workflow and point it at: %s\n' "$LEAN_DATA_DIRECTORY"
else
  printf 'LEAN CLI not installed; cannot stage LEAN datasets automatically.\n'
fi

printf 'Place curated JSONL news feeds under: %s\n' "$RUNTIME_ROOT/data/news_cache"
