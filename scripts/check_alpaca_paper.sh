#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  printf 'python3 is required for Alpaca paper validation.\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
from typing import Any, Dict

import requests

api_key = os.getenv("ALPACA_API_KEY", "").strip()
api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
environment = (os.getenv("ALPACA_ENVIRONMENT", "paper") or "paper").strip().lower()
trading_base_url = (os.getenv("ALPACA_TRADING_BASE_URL", "https://paper-api.alpaca.markets") or "").rstrip("/")

if not api_key or not api_secret:
    raise SystemExit("ALPACA_API_KEY and ALPACA_API_SECRET are required.")
if environment != "paper":
    raise SystemExit("ALPACA_ENVIRONMENT must be 'paper' for the first paper deployment path.")
if "paper-api.alpaca.markets" not in trading_base_url:
    raise SystemExit(
        "ALPACA_TRADING_BASE_URL must target the Alpaca paper endpoint for the first paper deployment path."
    )

headers = {
    "APCA-API-KEY-ID": api_key,
    "APCA-API-SECRET-KEY": api_secret,
}

def get(path: str) -> Dict[str, Any]:
    response = requests.get(f"{trading_base_url}{path}", headers=headers, timeout=15)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = response.text.strip()
        raise SystemExit(f"Alpaca request failed for {path}: {exc} body={detail}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise SystemExit(f"Unexpected Alpaca payload for {path}: {payload!r}")
    return payload

account = get("/v2/account")
clock = get("/v2/clock")
account_number = str(account.get("account_number", ""))
masked_account = f"...{account_number[-4:]}" if account_number else ""

summary = {
    "environment": environment,
    "trading_base_url": trading_base_url,
    "account_id": account.get("id"),
    "account_number": masked_account,
    "status": account.get("status"),
    "currency": account.get("currency"),
    "buying_power": account.get("buying_power"),
    "equity": account.get("equity"),
    "trading_blocked": account.get("trading_blocked"),
    "account_blocked": account.get("account_blocked"),
    "transfers_blocked": account.get("transfers_blocked"),
    "shorting_enabled": account.get("shorting_enabled"),
    "clock_is_open": clock.get("is_open"),
    "next_open": clock.get("next_open"),
    "next_close": clock.get("next_close"),
}

print(json.dumps(summary, indent=2, sort_keys=True))
PY
