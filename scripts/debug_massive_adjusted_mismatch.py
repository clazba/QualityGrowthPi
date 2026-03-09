#!/usr/bin/env python3
"""Print the worst Massive flat-file adjustment mismatches for one symbol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.provider_adapters.base import ProviderError
from src.stat_arb.massive_validation import (
    apply_massive_historical_adjustments,
    build_mismatch_samples,
    fetch_massive_corporate_actions,
    fetch_massive_rest_adjusted_series,
    load_massive_flatfile_close_series,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="Ticker to debug")
    parser.add_argument(
        "--flatfiles-root",
        default="data/massive/flatfiles/us_stocks_sip/day_aggs_v1",
        help="Root directory containing Massive day aggregate flat files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum mismatch rows to print.",
    )
    parser.add_argument(
        "--mode",
        choices=("split_only", "total_adjusted"),
        default="split_only",
        help="Whether to debug split-only reconstruction or total adjusted reconstruction.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON output path for the mismatch payload.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbol = args.symbol.strip().upper()
    include_dividends = args.mode == "total_adjusted"

    raw_series = load_massive_flatfile_close_series(symbol, args.flatfiles_root)
    actions = fetch_massive_corporate_actions(symbol, start_date=min(raw_series.closes_by_date))
    adjusted_series = apply_massive_historical_adjustments(
        raw_series,
        actions,
        include_dividends=include_dividends,
    )
    rest_series = fetch_massive_rest_adjusted_series(
        symbol,
        start_date=min(adjusted_series.closes_by_date),
        end_date=max(adjusted_series.closes_by_date),
    )
    samples = [
        sample.as_dict()
        for sample in build_mismatch_samples(
            raw_series,
            adjusted_series,
            rest_series,
            actions,
            limit=args.limit,
            include_dividends=include_dividends,
        )
    ]

    payload = {
        "symbol": symbol,
        "mode": args.mode,
        "flatfiles_root": str(Path(args.flatfiles_root).expanduser().resolve()),
        "date_range": {
            "start": min(raw_series.closes_by_date),
            "end": max(raw_series.closes_by_date),
        },
        "action_count": len(actions),
        "top_rest_mismatches": samples,
    }
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProviderError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
