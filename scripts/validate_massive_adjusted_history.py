#!/usr/bin/env python3
"""Validate Massive flat-file adjusted closes against Massive REST and Alpaca."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.provider_adapters.base import ProviderError
from src.stat_arb.massive_validation import validate_massive_adjusted_history
from src.strategy_settings import load_stat_arb_settings

DEFAULT_SYMBOLS = list(load_stat_arb_settings().universe.symbols)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--flatfiles-root",
        default="data/massive/flatfiles/us_stocks_sip/day_aggs_v1",
        help="Root directory containing Massive day aggregate flat files.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Symbols to validate. Defaults to the full stat-arb universe from strategy settings.",
    )
    parser.add_argument(
        "--settings-profile",
        default="default",
        help="Stat-arb settings profile used only when --symbols is omitted.",
    )
    parser.add_argument(
        "--recent-validation-days",
        type=int,
        default=60,
        help="Recent local trading days to compare against Alpaca.",
    )
    parser.add_argument(
        "--minimum-recent-overlap-days",
        type=int,
        default=10,
        help="Minimum local recent days required before Alpaca comparison is attempted.",
    )
    parser.add_argument(
        "--output",
        default="data/massive/validation/massive_adjusted_history_report.json",
        help="Destination JSON report path.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols = args.symbols if args.symbols else list(load_stat_arb_settings(args.settings_profile).universe.symbols)
    report = validate_massive_adjusted_history(
        symbols,
        flatfiles_root=args.flatfiles_root,
        recent_validation_days=args.recent_validation_days,
        minimum_recent_overlap_days=args.minimum_recent_overlap_days,
    )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    summary = {
        "output": str(output_path),
        "overall_status": report["overall_status"],
        "symbols": {symbol: payload["status"] for symbol, payload in report["reports"].items()},
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["overall_status"] != "failed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProviderError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
