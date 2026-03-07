#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
fi

printf 'LLM enabled: %s\n' "${QUANT_GPT_ENABLE_LLM:-unset}"
printf 'LLM mode: %s\n' "${QUANT_GPT_LLM_MODE:-unset}"
printf 'Gemini model: %s\n' "${GEMINI_MODEL_ID:-unset}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  printf 'Gemini API key is not configured. Offline contract tests can still run.\n'
  exit 0
fi

"$PYTHON_BIN" - <<'PY'
from pathlib import Path
from src.sentiment.schemas import load_schema

schema = load_schema(Path("config/prompts/extraction_schema.json"))
print(f"Loaded advisory schema with {len(schema['properties'])} properties")
PY
