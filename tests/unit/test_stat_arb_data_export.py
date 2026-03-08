from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.stat_arb import data_export
from src.stat_arb.data_export import (
    ProviderPriceSeries,
    export_aligned_price_history,
    export_provider_validated_price_history,
    load_symbol_price_series,
)
from src.provider_adapters.base import ProviderError


def _write_symbol_zip(root: Path, symbol: str, rows: list[str]) -> None:
    daily_dir = root / "equity" / "usa" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    archive_path = daily_dir / f"{symbol.lower()}.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(f"{symbol.lower()}.csv", "\n".join(rows) + "\n")


def _provider_series(
    symbol: str,
    closes: list[float],
    *,
    provider: str,
    start: str = "2024-01-02",
) -> ProviderPriceSeries:
    current = datetime.fromisoformat(start)
    closes_by_date: dict[str, float] = {}
    for close in closes:
        closes_by_date[current.date().isoformat()] = float(close)
        current += timedelta(days=1)
    return ProviderPriceSeries(
        symbol=symbol,
        provider=provider,
        closes_by_date=closes_by_date,
        volumes_by_date={date: 1_000_000.0 for date in closes_by_date},
        metadata={"test_fixture": True},
    )


def test_load_symbol_price_series_reads_lean_zip_payload(tmp_path: Path) -> None:
    _write_symbol_zip(
        tmp_path,
        "AAPL",
        [
            "20240102,100,101,99,100.5,1000000",
            "20240103,100,102,99,101.5,1100000",
            "20240104,101,103,100,102.5,1200000",
            "20240105,102,104,101,103.5,1200000",
            "20240108,103,105,102,104.5,1200000",
            "20240109,104,106,103,105.5,1200000",
            "20240110,105,107,104,106.5,1200000",
            "20240111,106,108,105,107.5,1200000",
            "20240112,107,109,106,108.5,1200000",
            "20240115,108,110,107,109.5,1200000",
        ],
    )

    series = load_symbol_price_series(tmp_path, "AAPL")

    assert series.symbol == "AAPL"
    assert series.closes_by_date["2024-01-02"] == 100.5
    assert series.closes_by_date["2024-01-15"] == 109.5


def test_export_aligned_price_history_intersects_calendar(tmp_path: Path) -> None:
    _write_symbol_zip(
        tmp_path,
        "AAPL",
        [
            "20240102,100,101,99,100.5,1000000",
            "20240103,100,102,99,101.5,1100000",
            "20240104,101,103,100,102.5,1200000",
            "20240105,102,104,101,103.5,1200000",
            "20240108,103,105,102,104.5,1200000",
            "20240109,104,106,103,105.5,1200000",
            "20240110,105,107,104,106.5,1200000",
            "20240111,106,108,105,107.5,1200000",
            "20240112,107,109,106,108.5,1200000",
            "20240115,108,110,107,109.5,1200000",
        ],
    )
    _write_symbol_zip(
        tmp_path,
        "MSFT",
        [
            "20240103,200,201,199,200.5,1000000",
            "20240104,200,202,199,201.5,1100000",
            "20240105,201,203,200,202.5,1200000",
            "20240108,202,204,201,203.5,1200000",
            "20240109,203,205,202,204.5,1200000",
            "20240110,204,206,203,205.5,1200000",
            "20240111,205,207,204,206.5,1200000",
            "20240112,206,208,205,207.5,1200000",
            "20240115,207,209,206,208.5,1200000",
            "20240116,208,210,207,209.5,1200000",
        ],
    )

    payload = export_aligned_price_history(tmp_path, ["AAPL", "MSFT"], minimum_common_days=5)

    assert payload["calendar"][0] == "2024-01-03"
    assert payload["calendar"][-1] == "2024-01-15"
    assert len(payload["calendar"]) == 9
    assert payload["price_history"]["AAPL"][0] == 101.5
    assert payload["price_history"]["MSFT"][0] == 200.5


def test_provider_export_prefers_primary_when_validation_passes(monkeypatch) -> None:
    primary_aapl = _provider_series("AAPL", [100, 101, 102, 103, 104, 105], provider="massive")
    primary_msft = _provider_series("MSFT", [200, 201, 202, 203, 204, 205], provider="massive")
    validator_aapl = _provider_series("AAPL", [100, 101, 102, 103, 104.1, 105.0], provider="alpaca")
    validator_msft = _provider_series("MSFT", [200, 201, 202, 203, 204.1, 205.0], provider="alpaca")

    def fake_fetcher(provider: str):
        def _fetch(symbol: str, lookback_days: int) -> ProviderPriceSeries:
            mapping = {
                ("massive", "AAPL"): primary_aapl,
                ("massive", "MSFT"): primary_msft,
                ("alpaca", "AAPL"): validator_aapl,
                ("alpaca", "MSFT"): validator_msft,
                ("alpha_vantage", "AAPL"): primary_aapl,
                ("alpha_vantage", "MSFT"): primary_msft,
            }
            return mapping[(provider, symbol)]

        return _fetch

    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "massive", fake_fetcher("massive"))
    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "alpaca", fake_fetcher("alpaca"))
    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "alpha_vantage", fake_fetcher("alpha_vantage"))

    payload = export_provider_validated_price_history(
        ["AAPL", "MSFT"],
        lookback_days=6,
        minimum_history_days=5,
        minimum_common_days=5,
        validation_window_days=5,
        minimum_validator_overlap_days=4,
        max_mean_abs_return_drift_bps=50.0,
        max_max_abs_return_drift_bps=150.0,
        max_latest_close_drift_bps=25.0,
    )

    metadata = payload["metadata"]
    assert metadata["export_mode"] == "provider_validated"
    assert metadata["symbols_included"] == ["AAPL", "MSFT"]
    assert metadata["symbol_provenance"]["AAPL"]["chosen_provider"] == "massive"
    assert metadata["symbol_provenance"]["AAPL"]["chosen_reason"] == "primary_validated"
    assert payload["price_history"]["AAPL"][-1] == 105.0


def test_provider_export_repairs_symbol_when_primary_fails_validation(monkeypatch) -> None:
    bad_primary_aapl = _provider_series("AAPL", [100, 101, 102, 103, 52, 53], provider="massive")
    validator_aapl = _provider_series("AAPL", [100, 101, 102, 103, 104, 105], provider="alpaca")
    repair_aapl = _provider_series("AAPL", [100, 101, 102, 103, 104, 105], provider="alpha_vantage")
    primary_msft = _provider_series("MSFT", [200, 201, 202, 203, 204, 205], provider="massive")
    validator_msft = _provider_series("MSFT", [200, 201, 202, 203, 204, 205], provider="alpaca")

    def fake_fetch(provider: str, symbol: str, lookback_days: int) -> ProviderPriceSeries:
        mapping = {
            ("massive", "AAPL"): bad_primary_aapl,
            ("alpaca", "AAPL"): validator_aapl,
            ("alpha_vantage", "AAPL"): repair_aapl,
            ("massive", "MSFT"): primary_msft,
            ("alpaca", "MSFT"): validator_msft,
            ("alpha_vantage", "MSFT"): primary_msft,
        }
        return mapping[(provider, symbol)]

    monkeypatch.setitem(
        data_export.PROVIDER_FETCHERS,
        "massive",
        lambda symbol, lookback_days: fake_fetch("massive", symbol, lookback_days),
    )
    monkeypatch.setitem(
        data_export.PROVIDER_FETCHERS,
        "alpaca",
        lambda symbol, lookback_days: fake_fetch("alpaca", symbol, lookback_days),
    )
    monkeypatch.setitem(
        data_export.PROVIDER_FETCHERS,
        "alpha_vantage",
        lambda symbol, lookback_days: fake_fetch("alpha_vantage", symbol, lookback_days),
    )

    payload = export_provider_validated_price_history(
        ["AAPL", "MSFT"],
        lookback_days=6,
        minimum_history_days=5,
        minimum_common_days=5,
        validation_window_days=5,
        minimum_validator_overlap_days=4,
        max_mean_abs_return_drift_bps=25.0,
        max_max_abs_return_drift_bps=100.0,
        max_latest_close_drift_bps=10.0,
    )

    assert payload["metadata"]["symbol_provenance"]["AAPL"]["chosen_provider"] == "alpha_vantage"
    assert payload["metadata"]["symbol_provenance"]["AAPL"]["chosen_reason"] == "repair_validated"
    assert payload["price_history"]["AAPL"][-1] == 105.0


def test_provider_export_excludes_symbol_without_validated_series(monkeypatch) -> None:
    validator_aapl = _provider_series("AAPL", [100, 101, 102, 103, 104, 105], provider="alpaca")
    primary_msft = _provider_series("MSFT", [200, 201, 202, 203, 204, 205], provider="massive")
    validator_msft = _provider_series("MSFT", [200, 201, 202, 203, 204, 205], provider="alpaca")

    def fake_massive(symbol: str, lookback_days: int) -> ProviderPriceSeries:
        if symbol == "AAPL":
            raise ProviderError("massive unavailable")
        return primary_msft

    def fake_alpaca(symbol: str, lookback_days: int) -> ProviderPriceSeries:
        if symbol == "AAPL":
            return validator_aapl
        return validator_msft

    def fake_alpha(symbol: str, lookback_days: int) -> ProviderPriceSeries:
        raise ProviderError("alpha unavailable")

    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "massive", fake_massive)
    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "alpaca", fake_alpaca)
    monkeypatch.setitem(data_export.PROVIDER_FETCHERS, "alpha_vantage", fake_alpha)

    with pytest.raises(ValueError, match="fewer than two validated symbols"):
        export_provider_validated_price_history(
            ["AAPL", "MSFT"],
            lookback_days=6,
            minimum_history_days=5,
            minimum_common_days=5,
            validation_window_days=5,
            minimum_validator_overlap_days=4,
        )
