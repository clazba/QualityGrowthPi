from __future__ import annotations

import csv
import gzip
from pathlib import Path

from src.stat_arb.data_export import ProviderPriceSeries
from src.stat_arb.massive_validation import (
    MassiveCorporateAction,
    SeriesDriftReport,
    apply_massive_historical_adjustments,
    build_mismatch_samples,
    compute_adjustment_factors_by_date,
    identify_isolated_rest_repairs,
    load_massive_flatfile_close_series,
    reconcile_dividend_only_alpaca_comparison,
    validate_massive_adjusted_history,
)


def _write_day_file(root: Path, year: int, month: int, day: int, rows: list[dict[str, object]]) -> None:
    target_dir = root / f"{year:04d}" / f"{month:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{year:04d}-{month:02d}-{day:02d}.csv.gz"
    with gzip.open(target, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "volume", "open", "close", "high", "low", "window_start", "transactions"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_load_massive_flatfile_close_series_reads_downloaded_csv_gz(tmp_path: Path) -> None:
    _write_day_file(
        tmp_path,
        2024,
        6,
        10,
        [
            {
                "ticker": "NVDA",
                "volume": 100,
                "open": 120.37,
                "close": 121.79,
                "high": 195.95,
                "low": 117.01,
                "window_start": 1717992000000000000,
                "transactions": 10,
            }
        ],
    )
    _write_day_file(
        tmp_path,
        2024,
        6,
        11,
        [
            {
                "ticker": "NVDA",
                "volume": 100,
                "open": 121.77,
                "close": 120.91,
                "high": 122.87,
                "low": 118.74,
                "window_start": 1718078400000000000,
                "transactions": 10,
            }
        ],
    )

    series = load_massive_flatfile_close_series("NVDA", tmp_path)

    assert series.provider == "massive_flatfiles_raw"
    assert series.closes_by_date == {
        "2024-06-10": 121.79,
        "2024-06-11": 120.91,
    }
    assert series.metadata["files_with_symbol"] == 2


def test_apply_massive_historical_adjustments_uses_post_action_cumulative_factor() -> None:
    raw_series = ProviderPriceSeries(
        symbol="NVDA",
        provider="massive_flatfiles_raw",
        closes_by_date={
            "2024-06-07": 1203.70,
            "2024-06-10": 121.79,
            "2024-06-11": 120.91,
        },
        metadata={},
    )
    actions = [
        MassiveCorporateAction(
            symbol="NVDA",
            action_type="split",
            action_date="2024-06-10",
            historical_adjustment_factor=0.1,
        )
    ]

    adjusted = apply_massive_historical_adjustments(raw_series, actions, include_dividends=False)

    assert adjusted.closes_by_date["2024-06-07"] == 120.37
    assert adjusted.closes_by_date["2024-06-10"] == 121.79
    assert adjusted.closes_by_date["2024-06-11"] == 120.91


def test_apply_massive_historical_adjustments_compounds_future_dividends_even_when_dates_are_missing() -> None:
    raw_series = ProviderPriceSeries(
        symbol="AAPL",
        provider="massive_flatfiles_raw",
        closes_by_date={
            "2026-02-10": 200.0,
            "2025-11-11": 190.0,
            "2025-08-12": 180.0,
            "2025-05-13": 170.0,
        },
        metadata={},
    )
    actions = [
        MassiveCorporateAction(
            symbol="AAPL",
            action_type="dividend",
            action_date="2025-05-12",
            historical_adjustment_factor=0.99566,
        ),
        MassiveCorporateAction(
            symbol="AAPL",
            action_type="dividend",
            action_date="2025-08-11",
            historical_adjustment_factor=0.996966,
        ),
        MassiveCorporateAction(
            symbol="AAPL",
            action_type="dividend",
            action_date="2025-11-10",
            historical_adjustment_factor=0.998098,
        ),
        MassiveCorporateAction(
            symbol="AAPL",
            action_type="dividend",
            action_date="2026-02-09",
            historical_adjustment_factor=0.999065,
        ),
    ]

    adjusted = apply_massive_historical_adjustments(raw_series, actions, include_dividends=True)

    assert adjusted.closes_by_date["2026-02-10"] == 200.0
    assert adjusted.closes_by_date["2025-11-11"] == 190.0 * 0.999065
    assert adjusted.closes_by_date["2025-08-12"] == 180.0 * (0.999065 * 0.998098)
    assert adjusted.closes_by_date["2025-05-13"] == 170.0 * (0.999065 * 0.998098 * 0.996966)


def test_compute_adjustment_factors_handles_missing_action_dates() -> None:
    factors = compute_adjustment_factors_by_date(
        ["2025-05-13", "2025-08-12", "2025-11-11", "2026-02-10"],
        [
            MassiveCorporateAction("AAPL", "dividend", "2025-05-12", 0.99566),
            MassiveCorporateAction("AAPL", "dividend", "2025-08-11", 0.996966),
            MassiveCorporateAction("AAPL", "dividend", "2025-11-10", 0.998098),
            MassiveCorporateAction("AAPL", "dividend", "2026-02-09", 0.999065),
        ],
        include_dividends=True,
    )

    assert factors["2026-02-10"] == 1.0
    assert factors["2025-11-11"] == 0.999065
    assert factors["2025-08-12"] == 0.999065 * 0.998098
    assert factors["2025-05-13"] == 0.999065 * 0.998098 * 0.996966


def test_build_mismatch_samples_surfaces_future_actions() -> None:
    raw_series = ProviderPriceSeries(
        symbol="NVDA",
        provider="massive_flatfiles_raw",
        closes_by_date={
            "2024-06-07": 1203.70,
            "2024-06-10": 121.79,
        },
        metadata={},
    )
    adjusted_series = apply_massive_historical_adjustments(
        raw_series,
        [MassiveCorporateAction("NVDA", "split", "2024-06-10", 0.1)],
        include_dividends=False,
    )
    rest_series = ProviderPriceSeries(
        symbol="NVDA",
        provider="massive_rest_adjusted",
        closes_by_date={
            "2024-06-07": 121.00,
            "2024-06-10": 121.79,
        },
        metadata={},
    )

    samples = build_mismatch_samples(
        raw_series,
        adjusted_series,
        rest_series,
        [MassiveCorporateAction("NVDA", "split", "2024-06-10", 0.1)],
        limit=2,
        include_dividends=False,
    )

    assert samples[0].trading_date == "2024-06-07"
    assert samples[0].future_actions[0]["action_date"] == "2024-06-10"
    assert samples[0].adjustment_factor == 0.1


def test_validate_massive_adjusted_history_reports_pass(monkeypatch, tmp_path: Path) -> None:
    flatfiles_root = tmp_path / "flatfiles"
    _write_day_file(
        flatfiles_root,
        2024,
        6,
        7,
        [
            {
                "ticker": "NVDA",
                "volume": 100,
                "open": 1203.70,
                "close": 1203.70,
                "high": 1203.70,
                "low": 1203.70,
                "window_start": 1717718400000000000,
                "transactions": 1,
            }
        ],
    )
    _write_day_file(
        flatfiles_root,
        2024,
        6,
        10,
        [
            {
                "ticker": "NVDA",
                "volume": 100,
                "open": 121.79,
                "close": 121.79,
                "high": 121.79,
                "low": 121.79,
                "window_start": 1717977600000000000,
                "transactions": 1,
            }
        ],
    )
    _write_day_file(
        flatfiles_root,
        2024,
        6,
        11,
        [
            {
                "ticker": "NVDA",
                "volume": 100,
                "open": 120.91,
                "close": 120.91,
                "high": 120.91,
                "low": 120.91,
                "window_start": 1718064000000000000,
                "transactions": 1,
            }
        ],
    )

    monkeypatch.setattr(
        "src.stat_arb.massive_validation.fetch_massive_corporate_actions",
        lambda symbol, start_date=None: [
            MassiveCorporateAction(
                symbol=symbol,
                action_type="split",
                action_date="2024-06-10",
                historical_adjustment_factor=0.1,
            )
        ],
    )
    monkeypatch.setattr(
        "src.stat_arb.massive_validation.fetch_massive_rest_adjusted_series",
        lambda symbol, start_date, end_date: ProviderPriceSeries(
            symbol=symbol,
            provider="massive_rest_adjusted",
            closes_by_date={
                "2024-06-07": 120.37,
                "2024-06-10": 121.79,
                "2024-06-11": 120.91,
            },
            metadata={},
        ),
    )
    monkeypatch.setattr(
        "src.stat_arb.massive_validation.fetch_alpaca_adjusted_series",
        lambda symbol, start_date, end_date: ProviderPriceSeries(
            symbol=symbol,
            provider="alpaca_adjusted",
            closes_by_date={
                "2024-06-07": 120.37,
                "2024-06-10": 121.79,
                "2024-06-11": 120.91,
            },
            metadata={},
        ),
    )

    report = validate_massive_adjusted_history(
        ["NVDA"],
        flatfiles_root=flatfiles_root,
        recent_validation_days=3,
        minimum_recent_overlap_days=2,
    )

    assert report["overall_status"] == "passed"
    assert report["reports"]["NVDA"]["status"] == "passed"
    assert report["reports"]["NVDA"]["actions"]["count"] == 1
    assert report["reports"]["NVDA"]["split_only_vs_massive_rest"]["status"] == "passed"
    assert report["reports"]["NVDA"]["total_adjusted_vs_alpaca"]["status"] == "passed"


def test_validate_massive_adjusted_history_marks_partial_without_recent_alpaca_window(
    monkeypatch,
    tmp_path: Path,
) -> None:
    flatfiles_root = tmp_path / "flatfiles"
    _write_day_file(
        flatfiles_root,
        2024,
        6,
        10,
        [
            {
                "ticker": "AAPL",
                "volume": 100,
                "open": 190.0,
                "close": 190.0,
                "high": 190.0,
                "low": 190.0,
                "window_start": 1717977600000000000,
                "transactions": 1,
            }
        ],
    )

    monkeypatch.setattr("src.stat_arb.massive_validation.fetch_massive_corporate_actions", lambda symbol, start_date=None: [])
    monkeypatch.setattr(
        "src.stat_arb.massive_validation.fetch_massive_rest_adjusted_series",
        lambda symbol, start_date, end_date: ProviderPriceSeries(
            symbol=symbol,
            provider="massive_rest_adjusted",
            closes_by_date={"2024-06-10": 190.0},
            metadata={},
        ),
    )

    report = validate_massive_adjusted_history(
        ["AAPL"],
        flatfiles_root=flatfiles_root,
        recent_validation_days=1,
        minimum_recent_overlap_days=2,
    )

    assert report["overall_status"] == "partial"
    assert report["reports"]["AAPL"]["status"] == "partial"
    assert report["reports"]["AAPL"]["split_only_vs_massive_rest"]["status"] == "passed"
    assert report["reports"]["AAPL"]["total_adjusted_vs_alpaca"]["status"] == "skipped"


def test_identify_isolated_rest_repairs_flags_one_day_flatfile_anomaly() -> None:
    raw_series = ProviderPriceSeries(
        symbol="GOOGL",
        provider="massive_flatfiles_raw",
        closes_by_date={
            "2023-05-29": 121.5,
            "2023-05-30": 123.67,
            "2023-05-31": 122.9,
        },
        metadata={},
    )
    adjusted_series = ProviderPriceSeries(
        symbol="GOOGL",
        provider="massive_flatfiles_adjusted",
        closes_by_date=dict(raw_series.closes_by_date),
        metadata={},
    )
    rest_series = ProviderPriceSeries(
        symbol="GOOGL",
        provider="massive_rest_adjusted",
        closes_by_date={
            "2023-05-29": 121.5,
            "2023-05-30": 122.04,
            "2023-05-31": 122.9,
        },
        metadata={},
    )

    repairs = identify_isolated_rest_repairs(raw_series, adjusted_series, rest_series, [])

    assert len(repairs) == 1
    assert repairs[0]["trading_date"] == "2023-05-30"
    assert repairs[0]["raw_close_original"] == 123.67
    assert repairs[0]["raw_close_repaired"] == 122.04
    assert repairs[0]["validator_close"] == 122.04
    assert repairs[0]["adjustment_factor"] == 1.0
    assert repairs[0]["close_drift_bps"] > 50.0
    assert repairs[0]["reason"] == "isolated_massive_rest_mismatch"


def test_reconcile_dividend_only_alpaca_comparison_tolerates_level_drift_when_returns_align() -> None:
    comparison = SeriesDriftReport(
        provider="massive_flatfiles_adjusted",
        validator="alpaca_adjusted",
        status="failed",
        overlap_days=82,
        compared_return_days=81,
        mean_abs_close_drift_bps=16.0,
        max_abs_close_drift_bps=68.0,
        latest_close_drift_bps=2.6,
        mean_abs_return_drift_bps=3.9,
        max_abs_return_drift_bps=64.5,
        issues=[
            "mean_close_drift_bps:16.0000>10.0000",
            "max_close_drift_bps:68.0000>50.0000",
        ],
    )

    normalized, notes = reconcile_dividend_only_alpaca_comparison(
        [MassiveCorporateAction("QCOM", "dividend", "2025-12-04", 0.988569)],
        comparison,
    )

    assert normalized.status == "passed"
    assert normalized.issues == []
    assert notes == ["alpaca:dividend_only_close_level_drift_tolerated"]
