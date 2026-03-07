#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" -m pytest "$PROJECT_ROOT/tests/llm"
"$PROJECT_ROOT/scripts/llm_healthcheck.sh"

printf 'LLM smoke test completed successfully\n'
