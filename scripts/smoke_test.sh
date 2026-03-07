#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" -m src.main health
"$PYTHON_BIN" -m pytest -q "$PROJECT_ROOT/tests/unit/test_scoring.py" "$PROJECT_ROOT/tests/unit/test_timing.py"

printf 'Smoke test completed successfully\n'
