#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -m src.main llm-report
