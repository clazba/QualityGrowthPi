#!/usr/bin/env python3
"""Export aligned stat-arb training price history from LEAN-style daily data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stat_arb.data_export import export_aligned_price_history, write_price_history_json
from src.strategy_settings import load_stat_arb_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lean-data-root",
        default=str(PROJECT_ROOT / "data" / "lean"),
        help="Root of LEAN-style local data, e.g. data/lean",
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbol list. Defaults to the stat-arb universe from strategy settings.",
    )
    parser.add_argument(
        "--settings-profile",
        default="default",
        help="Stat-arb settings profile name for default universe selection",
    )
    parser.add_argument(
        "--minimum-common-days",
        type=int,
        default=60,
        help="Minimum aligned daily bars required across the requested symbols",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "stat_arb_training" / "stat_arb_price_history.json"),
        help="Output JSON path for the trainer input file",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    else:
        symbols = list(load_stat_arb_settings(args.settings_profile).universe.symbols)
    payload = export_aligned_price_history(
        args.lean_data_root,
        symbols,
        minimum_common_days=args.minimum_common_days,
    )
    output_path = write_price_history_json(payload, args.output)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "symbol_count": len(payload["price_history"]),
                "common_days": payload["metadata"]["common_days"],
                "symbols": payload["metadata"]["symbols"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
