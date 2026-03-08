#!/usr/bin/env python3
"""Export aligned stat-arb training price history for the offline ensemble."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stat_arb.data_export import (
    ProviderExportError,
    export_aligned_price_history,
    export_provider_validated_price_history,
    write_price_history_json,
)
from src.strategy_settings import load_stat_arb_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-mode",
        choices=("providers", "lean"),
        default="providers",
        help="Export from provider-backed daily bars (default) or legacy LEAN local files",
    )
    parser.add_argument(
        "--lean-data-root",
        default=str(PROJECT_ROOT / "data" / "lean"),
        help="Root of LEAN-style local data, used only when --source-mode=lean",
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
        default=252,
        help="Minimum aligned daily bars required across the requested symbols",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=756,
        help="History depth requested from provider-backed sources",
    )
    parser.add_argument(
        "--minimum-history-days",
        type=int,
        default=252,
        help="Minimum per-symbol history required before the trainer will accept the series",
    )
    parser.add_argument(
        "--primary-provider",
        default="massive",
        choices=("massive", "alpaca", "alpha_vantage"),
        help="Primary provider for full-history adjusted daily bars",
    )
    parser.add_argument(
        "--validator-provider",
        default="alpaca",
        choices=("massive", "alpaca", "alpha_vantage"),
        help="Recent-window validator used to catch bad adjustments or drift",
    )
    parser.add_argument(
        "--repair-provider",
        default="alpha_vantage",
        choices=("massive", "alpaca", "alpha_vantage"),
        help="Full-history fallback if the primary provider fails validation",
    )
    parser.add_argument(
        "--validation-window-days",
        type=int,
        default=60,
        help="How many most-recent overlapping days to compare against the validator source",
    )
    parser.add_argument(
        "--minimum-validator-overlap-days",
        type=int,
        default=30,
        help="Minimum overlapping recent days required for validator approval",
    )
    parser.add_argument(
        "--max-mean-abs-return-drift-bps",
        type=float,
        default=75.0,
        help="Maximum mean absolute return drift in basis points over the validation window",
    )
    parser.add_argument(
        "--max-max-abs-return-drift-bps",
        type=float,
        default=500.0,
        help="Maximum worst-case return drift in basis points over the validation window",
    )
    parser.add_argument(
        "--max-latest-close-drift-bps",
        type=float,
        default=250.0,
        help="Maximum latest close-level drift in basis points versus the validator source",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "stat_arb_training" / "stat_arb_price_history.json"),
        help="Output JSON path for the trainer input file",
    )
    parser.add_argument(
        "--diagnostics-output",
        help="Optional JSON path for exporter diagnostics when provider-backed validation fails",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = load_stat_arb_settings(args.settings_profile)
    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    else:
        symbols = list(settings.universe.symbols)
    diagnostics_output = Path(args.diagnostics_output).expanduser().resolve() if args.diagnostics_output else (
        Path(args.output).expanduser().resolve().with_name(Path(args.output).stem + "_diagnostics.json")
    )
    try:
        if args.source_mode == "lean":
            payload = export_aligned_price_history(
                args.lean_data_root,
                symbols,
                minimum_common_days=args.minimum_common_days,
            )
        else:
            payload = export_provider_validated_price_history(
                symbols,
                lookback_days=max(args.lookback_days, settings.universe.lookback_days),
                minimum_history_days=max(args.minimum_history_days, settings.universe.min_history_days),
                minimum_common_days=args.minimum_common_days,
                primary_provider=args.primary_provider,
                validator_provider=args.validator_provider,
                repair_provider=args.repair_provider,
                validation_window_days=args.validation_window_days,
                minimum_validator_overlap_days=args.minimum_validator_overlap_days,
                max_mean_abs_return_drift_bps=args.max_mean_abs_return_drift_bps,
                max_max_abs_return_drift_bps=args.max_max_abs_return_drift_bps,
                max_latest_close_drift_bps=args.max_latest_close_drift_bps,
            )
    except ProviderExportError as exc:
        diagnostics_output.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_output.write_text(json.dumps(exc.diagnostics, indent=2, sort_keys=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "diagnostics_output": str(diagnostics_output),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    output_path = write_price_history_json(payload, args.output)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "symbol_count": len(payload["price_history"]),
                "common_days": payload["metadata"]["common_days"],
                "symbols": payload["metadata"].get("symbols_included") or payload["metadata"]["symbols"],
                "export_mode": payload["metadata"]["export_mode"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
