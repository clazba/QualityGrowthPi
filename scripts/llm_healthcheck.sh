#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import os

from dotenv import load_dotenv
from src.sentiment.schemas import load_schema

env_path = Path(".env")
if env_path.exists():
    load_dotenv(env_path, override=False)

print(f"LLM enabled: {os.getenv('QUANT_GPT_ENABLE_LLM', 'unset')}")
print(f"LLM mode: {os.getenv('QUANT_GPT_LLM_MODE', 'unset')}")
print(f"Gemini model: {os.getenv('GEMINI_MODEL_ID', 'unset')}")

if not os.getenv("GEMINI_API_KEY"):
    print("Gemini API key is not configured. Offline contract tests can still run.")
    raise SystemExit(0)

schema = load_schema(Path("config/prompts/extraction_schema.json"))
print(f"Loaded advisory schema with {len(schema['properties'])} properties")
PY
