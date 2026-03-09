#!/usr/bin/env python3
"""Export aligned stat-arb training price history for the offline ensemble."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from datetime import UTC, datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stat_arb.data_export import (
    ProviderExportError,
    export_aligned_price_history,
    export_massive_flatfiles_price_history,
    export_provider_validated_price_history,
    set_progress_callback,
    write_price_history_json,
)
from src.strategy_settings import load_stat_arb_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-mode",
        choices=("providers", "lean", "massive_flatfiles"),
        default="providers",
        help="Export from provider-backed daily bars (default), validated Massive flat files, or legacy LEAN local files",
    )
    parser.add_argument(
        "--lean-data-root",
        default=str(PROJECT_ROOT / "data" / "lean"),
        help="Root of LEAN-style local data, used only when --source-mode=lean",
    )
    parser.add_argument(
        "--flatfiles-root",
        default=str(PROJECT_ROOT / "data" / "massive" / "flatfiles" / "us_stocks_sip" / "day_aggs_v1"),
        help="Root of downloaded Massive day aggregate flat files, used only when --source-mode=massive_flatfiles",
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
    parser.add_argument(
        "--validation-report",
        default="",
        help="Optional JSON path to a previously passed Massive validation report; used only when --source-mode=massive_flatfiles",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress live exporter progress output",
    )
    return parser.parse_args()


PROGRESS_PATTERN = re.compile(r"^\[(\d+)/(\d+)\]\s+")


def _progress_logger(message: str) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rendered = message
    match = PROGRESS_PATTERN.match(message)
    if match:
        current = int(match.group(1))
        total = max(int(match.group(2)), 1)
        width = 20
        filled = min(width, int(round((current / total) * width)))
        bar = "#" * filled + "-" * (width - filled)
        rendered = f"[{bar}] {message}"
    print(f"{timestamp} | {rendered}", file=sys.stderr, flush=True)


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
    validation_report = None
    if args.validation_report:
        validation_report = json.loads(Path(args.validation_report).expanduser().resolve().read_text(encoding="utf-8"))
    if not args.quiet:
        set_progress_callback(_progress_logger)
    try:
        if args.source_mode == "lean":
            payload = export_aligned_price_history(
                args.lean_data_root,
                symbols,
                minimum_common_days=args.minimum_common_days,
            )
        elif args.source_mode == "massive_flatfiles":
            payload = export_massive_flatfiles_price_history(
                symbols,
                flatfiles_root=args.flatfiles_root,
                minimum_common_days=args.minimum_common_days,
                recent_validation_days=args.validation_window_days,
                minimum_recent_overlap_days=args.minimum_validator_overlap_days,
                validation_report=validation_report,
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
    finally:
        set_progress_callback(None)
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
