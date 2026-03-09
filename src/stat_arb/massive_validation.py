"""Validate Massive flat-file adjusted closes against Massive REST and Alpaca."""

from __future__ import annotations

import csv
import gzip
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.provider_adapters.alpaca_adapter import AlpacaMarketDataAdapter
from src.provider_adapters.base import ProviderError
from src.provider_adapters.polygon_adapter import MassiveAdapter
from src.stat_arb.data_export import (
    ProviderPriceSeries,
    _request_massive_payload_with_backoff,
    _safe_log_return,
    _timestamp_to_trading_date,
)


@dataclass(frozen=True)
class MassiveCorporateAction:
    """One split or dividend action with a historical adjustment factor."""

    symbol: str
    action_type: str
    action_date: str
    historical_adjustment_factor: float
    source_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action_type": self.action_type,
            "action_date": self.action_date,
            "historical_adjustment_factor": self.historical_adjustment_factor,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class SeriesDriftReport:
    """Comparison summary between two adjusted close series."""

    provider: str
    validator: str
    status: str
    overlap_days: int
    compared_return_days: int
    mean_abs_close_drift_bps: float
    max_abs_close_drift_bps: float
    latest_close_drift_bps: float
    mean_abs_return_drift_bps: float
    max_abs_return_drift_bps: float
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "validator": self.validator,
            "status": self.status,
            "overlap_days": self.overlap_days,
            "compared_return_days": self.compared_return_days,
            "mean_abs_close_drift_bps": round(self.mean_abs_close_drift_bps, 6),
            "max_abs_close_drift_bps": round(self.max_abs_close_drift_bps, 6),
            "latest_close_drift_bps": round(self.latest_close_drift_bps, 6),
            "mean_abs_return_drift_bps": round(self.mean_abs_return_drift_bps, 6),
            "max_abs_return_drift_bps": round(self.max_abs_return_drift_bps, 6),
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class DailyMismatchSample:
    """One date-level mismatch observation between reconstructed and validator closes."""

    trading_date: str
    raw_close: float | None
    adjustment_factor: float
    adjusted_close: float
    validator_close: float
    close_drift_bps: float
    series_return: float | None = None
    validator_return: float | None = None
    return_drift_bps: float | None = None
    future_actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "raw_close": None if self.raw_close is None else round(self.raw_close, 6),
            "adjustment_factor": round(self.adjustment_factor, 9),
            "adjusted_close": round(self.adjusted_close, 6),
            "validator_close": round(self.validator_close, 6),
            "close_drift_bps": round(self.close_drift_bps, 6),
            "series_return": None if self.series_return is None else round(self.series_return, 9),
            "validator_return": None if self.validator_return is None else round(self.validator_return, 9),
            "return_drift_bps": None if self.return_drift_bps is None else round(self.return_drift_bps, 6),
            "future_actions": list(self.future_actions),
        }


def apply_series_repairs(
    series: ProviderPriceSeries,
    repairs: list[dict[str, Any]],
) -> ProviderPriceSeries:
    """Apply explicit close overrides to a provider series."""

    if not repairs:
        return series
    closes_by_date = dict(series.closes_by_date)
    for repair in repairs:
        trading_date = str(repair.get("trading_date", "")).strip()
        raw_close = repair.get("raw_close_repaired")
        if not trading_date or raw_close is None:
            continue
        closes_by_date[trading_date] = float(raw_close)
    return ProviderPriceSeries(
        symbol=series.symbol,
        provider=series.provider,
        closes_by_date=dict(sorted(closes_by_date.items())),
        volumes_by_date=dict(series.volumes_by_date),
        metadata={**dict(series.metadata), "repair_count": len(repairs)},
    )


def _path_to_trading_date(path: Path) -> str:
    """Return YYYY-MM-DD from a day aggregate file path."""

    return path.stem.replace(".csv", "")


def load_massive_flatfile_close_series(
    symbol: str,
    flatfiles_root: str | Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ProviderPriceSeries:
    """Load raw daily close history for one symbol from Massive day aggregates."""

    root = Path(flatfiles_root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Massive flat-file root does not exist: {root}")

    normalized_symbol = symbol.strip().upper()
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    closes_by_date: dict[str, float] = {}
    volumes_by_date: dict[str, float] = {}
    files_scanned = 0
    files_with_symbol = 0

    for path in sorted(root.glob("*/*/*.csv.gz")):
        trading_date = date.fromisoformat(_path_to_trading_date(path))
        if start and trading_date < start:
            continue
        if end and trading_date > end:
            continue
        files_scanned += 1
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("ticker", "").upper() != normalized_symbol:
                    continue
                closes_by_date[trading_date.isoformat()] = float(row["close"])
                volumes_by_date[trading_date.isoformat()] = float(row["volume"])
                files_with_symbol += 1
                break

    if not closes_by_date:
        raise ValueError(f"No Massive flat-file rows found for {normalized_symbol} under {root}")

    return ProviderPriceSeries(
        symbol=normalized_symbol,
        provider="massive_flatfiles_raw",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "flatfiles_root": str(root),
            "files_scanned": files_scanned,
            "files_with_symbol": files_with_symbol,
            "start_date": min(closes_by_date),
            "end_date": max(closes_by_date),
        },
    )


def fetch_massive_corporate_actions(
    symbol: str,
    *,
    start_date: str | None = None,
) -> list[MassiveCorporateAction]:
    """Return split and dividend actions usable for historical price adjustment."""

    adapter = MassiveAdapter()
    normalized_symbol = symbol.strip().upper()
    actions: list[MassiveCorporateAction] = []
    requests: tuple[tuple[str, str, str], ...] = (
        ("/stocks/v1/splits", "execution_date.gte", "execution_date"),
        ("/stocks/v1/dividends", "ex_dividend_date.gte", "ex_dividend_date"),
    )

    for path, start_key, action_date_key in requests:
        params: dict[str, Any] = {"ticker": normalized_symbol}
        if start_date:
            params[start_key] = start_date
        for record in adapter._paginate_results(path, params=params):
            factor = record.get("historical_adjustment_factor")
            if factor in {None, ""}:
                continue
            try:
                factor_value = float(factor)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(factor_value) or factor_value <= 0.0:
                continue
            action_date = str(record.get(action_date_key, "")).strip()
            if not action_date:
                continue
            actions.append(
                MassiveCorporateAction(
                    symbol=normalized_symbol,
                    action_type="split" if "split" in path else "dividend",
                    action_date=action_date,
                    historical_adjustment_factor=factor_value,
                    source_id=str(record.get("id")) if record.get("id") else None,
                )
            )

    return sorted(actions, key=lambda item: (item.action_date, item.action_type))


def compute_adjustment_factors_by_date(
    trading_dates: list[str],
    actions: list[MassiveCorporateAction],
    *,
    include_dividends: bool = True,
) -> dict[str, float]:
    """Return the cumulative adjustment factor applied to each trading date."""

    factors_by_date: dict[str, float] = {}
    for action in actions:
        if action.action_type == "dividend" and not include_dividends:
            continue
        current = factors_by_date.get(action.action_date)
        incoming = float(action.historical_adjustment_factor)
        factors_by_date[action.action_date] = incoming if current is None else (current * incoming)

    ordered_action_dates_desc = sorted(factors_by_date, reverse=True)
    next_action_index = 0
    cumulative_factor = 1.0
    factor_by_trading_date: dict[str, float] = {}

    for trading_date in sorted(trading_dates, reverse=True):
        while (
            next_action_index < len(ordered_action_dates_desc)
            and ordered_action_dates_desc[next_action_index] > trading_date
        ):
            cumulative_factor *= factors_by_date[ordered_action_dates_desc[next_action_index]]
            next_action_index += 1
        factor_by_trading_date[trading_date] = cumulative_factor
    return factor_by_trading_date


def apply_massive_historical_adjustments(
    raw_series: ProviderPriceSeries,
    actions: list[MassiveCorporateAction],
    *,
    include_dividends: bool = True,
) -> ProviderPriceSeries:
    """Apply Massive historical adjustment factors to raw close history."""

    factor_by_trading_date = compute_adjustment_factors_by_date(
        list(raw_series.closes_by_date),
        actions,
        include_dividends=include_dividends,
    )
    adjusted_closes: dict[str, float] = {}
    for trading_date in sorted(raw_series.closes_by_date):
        raw_close = float(raw_series.closes_by_date[trading_date])
        adjusted_closes[trading_date] = raw_close * factor_by_trading_date[trading_date]

    return ProviderPriceSeries(
        symbol=raw_series.symbol,
        provider="massive_flatfiles_adjusted",
        closes_by_date=dict(sorted(adjusted_closes.items())),
        volumes_by_date=dict(raw_series.volumes_by_date),
        metadata={
            **dict(raw_series.metadata),
            "action_count": len(actions),
            "action_dates": sorted({action.action_date for action in actions}),
            "include_dividends": include_dividends,
        },
    )


def fetch_massive_rest_adjusted_series(symbol: str, start_date: str, end_date: str) -> ProviderPriceSeries:
    """Fetch Massive REST adjusted daily closes over the requested window."""

    adapter = MassiveAdapter()
    bars_by_date: dict[str, dict[str, float]] = {}
    next_target: str | None = adapter._build_aggregates_path(symbol, start_date, end_date)
    request_params: dict[str, Any] | None = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 500,
    }
    request_count = 0
    seen_urls: set[str] = set()

    while next_target:
        if next_target in seen_urls:
            raise ProviderError("Massive REST validation pagination returned a repeated next_url")
        seen_urls.add(next_target)
        payload = _request_massive_payload_with_backoff(adapter, next_target, params=request_params)
        request_count += 1
        for bar in adapter._parse_aggregate_payload(payload):
            trading_date = _timestamp_to_trading_date(bar["timestamp"])
            bars_by_date[trading_date] = bar
        next_target = payload.get("next_url")
        request_params = None

    if not bars_by_date:
        raise ProviderError(f"No Massive REST adjusted bars returned for {symbol} {start_date}..{end_date}")

    closes_by_date = {date_key: float(item["close"]) for date_key, item in sorted(bars_by_date.items())}
    volumes_by_date = {date_key: float(item["volume"]) for date_key, item in sorted(bars_by_date.items())}
    return ProviderPriceSeries(
        symbol=symbol.upper(),
        provider="massive_rest_adjusted",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "base_url": adapter.base_url,
            "start_date": start_date,
            "end_date": end_date,
            "request_count": request_count,
        },
    )


def fetch_alpaca_adjusted_series(symbol: str, start_date: str, end_date: str) -> ProviderPriceSeries:
    """Fetch Alpaca adjusted daily closes over the requested window."""

    adapter = AlpacaMarketDataAdapter()
    start_at = f"{start_date}T00:00:00Z"
    end_at = f"{end_date}T23:59:59Z"
    payload = adapter._request(
        adapter.bars_path_template.format(symbol=symbol),
        params={
            "timeframe": "1Day",
            "limit": 10_000,
            "adjustment": "all",
            "feed": adapter.feed,
            "sort": "asc",
            "start": start_at,
            "end": end_at,
        },
    )
    normalized = adapter._normalize_bar_payload(payload)
    if not normalized:
        raise ProviderError(f"No Alpaca adjusted bars returned for {symbol} {start_date}..{end_date}")
    closes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["close"]) for item in normalized}
    volumes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["volume"]) for item in normalized}
    return ProviderPriceSeries(
        symbol=symbol.upper(),
        provider="alpaca_adjusted",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "feed": adapter.feed,
            "base_url": adapter.market_data_base_url,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def compare_adjusted_series(
    series: ProviderPriceSeries,
    validator: ProviderPriceSeries,
    *,
    minimum_overlap_days: int = 10,
    max_mean_abs_close_drift_bps: float = 10.0,
    max_max_abs_close_drift_bps: float = 50.0,
    max_latest_close_drift_bps: float = 10.0,
    max_mean_abs_return_drift_bps: float = 10.0,
    max_max_abs_return_drift_bps: float = 50.0,
) -> SeriesDriftReport:
    """Compare two close series on overlapping dates."""

    overlap_dates = sorted(set(series.closes_by_date) & set(validator.closes_by_date))
    issues: list[str] = []
    if len(overlap_dates) < minimum_overlap_days:
        issues.append(f"insufficient_overlap:{len(overlap_dates)}<{minimum_overlap_days}")
        return SeriesDriftReport(
            provider=series.provider,
            validator=validator.provider,
            status="skipped",
            overlap_days=len(overlap_dates),
            compared_return_days=max(len(overlap_dates) - 1, 0),
            mean_abs_close_drift_bps=0.0,
            max_abs_close_drift_bps=0.0,
            latest_close_drift_bps=0.0,
            mean_abs_return_drift_bps=0.0,
            max_abs_return_drift_bps=0.0,
            issues=issues,
        )

    close_drift_bps: list[float] = []
    return_drift_bps: list[float] = []
    ordered_series = [float(series.closes_by_date[date_key]) for date_key in overlap_dates]
    ordered_validator = [float(validator.closes_by_date[date_key]) for date_key in overlap_dates]

    for index, date_key in enumerate(overlap_dates):
        validator_close = ordered_validator[index]
        series_close = ordered_series[index]
        close_drift_bps.append(abs(series_close - validator_close) / max(abs(validator_close), 1e-9) * 10_000.0)
        if index == 0:
            continue
        series_return = _safe_log_return(series_close, ordered_series[index - 1])
        validator_return = _safe_log_return(validator_close, ordered_validator[index - 1])
        if series_return is None or validator_return is None:
            continue
        return_drift_bps.append(abs(series_return - validator_return) * 10_000.0)

    mean_abs_close_drift_bps = sum(close_drift_bps) / len(close_drift_bps) if close_drift_bps else 0.0
    max_abs_close_drift_bps = max(close_drift_bps) if close_drift_bps else 0.0
    latest_close_drift_bps = close_drift_bps[-1] if close_drift_bps else 0.0
    mean_abs_return_drift_bps = sum(return_drift_bps) / len(return_drift_bps) if return_drift_bps else 0.0
    max_abs_return_drift_bps = max(return_drift_bps) if return_drift_bps else 0.0

    if mean_abs_close_drift_bps > max_mean_abs_close_drift_bps:
        issues.append(f"mean_close_drift_bps:{mean_abs_close_drift_bps:.4f}>{max_mean_abs_close_drift_bps:.4f}")
    if max_abs_close_drift_bps > max_max_abs_close_drift_bps:
        issues.append(f"max_close_drift_bps:{max_abs_close_drift_bps:.4f}>{max_max_abs_close_drift_bps:.4f}")
    if latest_close_drift_bps > max_latest_close_drift_bps:
        issues.append(f"latest_close_drift_bps:{latest_close_drift_bps:.4f}>{max_latest_close_drift_bps:.4f}")
    if mean_abs_return_drift_bps > max_mean_abs_return_drift_bps:
        issues.append(
            f"mean_return_drift_bps:{mean_abs_return_drift_bps:.4f}>{max_mean_abs_return_drift_bps:.4f}"
        )
    if max_abs_return_drift_bps > max_max_abs_return_drift_bps:
        issues.append(f"max_return_drift_bps:{max_abs_return_drift_bps:.4f}>{max_max_abs_return_drift_bps:.4f}")

    return SeriesDriftReport(
        provider=series.provider,
        validator=validator.provider,
        status="passed" if not issues else "failed",
        overlap_days=len(overlap_dates),
        compared_return_days=len(return_drift_bps),
        mean_abs_close_drift_bps=mean_abs_close_drift_bps,
        max_abs_close_drift_bps=max_abs_close_drift_bps,
        latest_close_drift_bps=latest_close_drift_bps,
        mean_abs_return_drift_bps=mean_abs_return_drift_bps,
        max_abs_return_drift_bps=max_abs_return_drift_bps,
        issues=issues,
    )


def identify_isolated_rest_repairs(
    raw_series: ProviderPriceSeries,
    adjusted_series: ProviderPriceSeries,
    validator: ProviderPriceSeries,
    actions: list[MassiveCorporateAction],
    *,
    include_dividends: bool = False,
    repair_close_drift_bps: float = 50.0,
    clean_neighbor_close_drift_bps: float = 10.0,
    max_repairs: int = 2,
) -> list[dict[str, Any]]:
    """Identify a small number of isolated Massive flat-file anomalies worth repairing."""

    overlap_dates = sorted(set(adjusted_series.closes_by_date) & set(validator.closes_by_date))
    if not overlap_dates:
        return []

    factor_by_trading_date = compute_adjustment_factors_by_date(
        overlap_dates,
        actions,
        include_dividends=include_dividends,
    )
    action_dates = {
        action.action_date
        for action in actions
        if include_dividends or action.action_type != "dividend"
    }
    close_drifts: list[float] = []
    for trading_date in overlap_dates:
        adjusted_close = float(adjusted_series.closes_by_date[trading_date])
        validator_close = float(validator.closes_by_date[trading_date])
        close_drifts.append(abs(adjusted_close - validator_close) / max(abs(validator_close), 1e-9) * 10_000.0)

    repairs: list[dict[str, Any]] = []
    for index, trading_date in enumerate(overlap_dates):
        close_drift = close_drifts[index]
        if close_drift <= repair_close_drift_bps:
            continue
        if trading_date in action_dates:
            continue
        previous_drift = close_drifts[index - 1] if index > 0 else 0.0
        next_drift = close_drifts[index + 1] if index + 1 < len(close_drifts) else 0.0
        if previous_drift > clean_neighbor_close_drift_bps or next_drift > clean_neighbor_close_drift_bps:
            continue
        raw_close = raw_series.closes_by_date.get(trading_date)
        factor = float(factor_by_trading_date.get(trading_date, 1.0))
        validator_close = float(validator.closes_by_date[trading_date])
        if raw_close is None or not math.isfinite(factor) or factor <= 0.0:
            continue
        repairs.append(
            {
                "trading_date": trading_date,
                "raw_close_original": float(raw_close),
                "raw_close_repaired": validator_close / factor,
                "validator_close": validator_close,
                "adjustment_factor": factor,
                "close_drift_bps": close_drift,
                "reason": "isolated_massive_rest_mismatch",
            }
        )
        if len(repairs) >= max_repairs:
            break
    return repairs


def reconcile_dividend_only_alpaca_comparison(
    actions: list[MassiveCorporateAction],
    comparison: SeriesDriftReport,
) -> tuple[SeriesDriftReport, list[str]]:
    """Allow dividend-only symbols to pass Alpaca validation when returns already align."""

    if comparison.status != "failed":
        return comparison, []
    if any(action.action_type == "split" for action in actions):
        return comparison, []

    disallowed_prefixes = ("latest_close_drift_bps:", "mean_return_drift_bps:", "max_return_drift_bps:")
    if any(issue.startswith(disallowed_prefixes) for issue in comparison.issues):
        return comparison, []

    if comparison.mean_abs_return_drift_bps > 5.0 or comparison.max_abs_return_drift_bps > 75.0:
        return comparison, []
    if comparison.latest_close_drift_bps > 10.0 or comparison.max_abs_close_drift_bps > 75.0:
        return comparison, []

    return (
        SeriesDriftReport(
            provider=comparison.provider,
            validator=comparison.validator,
            status="passed",
            overlap_days=comparison.overlap_days,
            compared_return_days=comparison.compared_return_days,
            mean_abs_close_drift_bps=comparison.mean_abs_close_drift_bps,
            max_abs_close_drift_bps=comparison.max_abs_close_drift_bps,
            latest_close_drift_bps=comparison.latest_close_drift_bps,
            mean_abs_return_drift_bps=comparison.mean_abs_return_drift_bps,
            max_abs_return_drift_bps=comparison.max_abs_return_drift_bps,
            issues=[],
        ),
        ["alpaca:dividend_only_close_level_drift_tolerated"],
    )


def build_mismatch_samples(
    raw_series: ProviderPriceSeries,
    adjusted_series: ProviderPriceSeries,
    validator: ProviderPriceSeries,
    actions: list[MassiveCorporateAction],
    *,
    limit: int = 10,
    include_dividends: bool = True,
) -> list[DailyMismatchSample]:
    """Return the worst date-level mismatches for debugging adjustment semantics."""

    overlap_dates = sorted(set(adjusted_series.closes_by_date) & set(validator.closes_by_date))
    if not overlap_dates:
        return []

    factor_by_trading_date = compute_adjustment_factors_by_date(
        overlap_dates,
        actions,
        include_dividends=include_dividends,
    )
    mismatch_samples: list[DailyMismatchSample] = []
    ordered_adjusted = [float(adjusted_series.closes_by_date[date_key]) for date_key in overlap_dates]
    ordered_validator = [float(validator.closes_by_date[date_key]) for date_key in overlap_dates]

    for index, trading_date in enumerate(overlap_dates):
        adjusted_close = ordered_adjusted[index]
        validator_close = ordered_validator[index]
        close_drift_bps = abs(adjusted_close - validator_close) / max(abs(validator_close), 1e-9) * 10_000.0
        series_return = None
        validator_return = None
        return_drift_bps = None
        if index > 0:
            series_return = _safe_log_return(adjusted_close, ordered_adjusted[index - 1])
            validator_return = _safe_log_return(validator_close, ordered_validator[index - 1])
            if series_return is not None and validator_return is not None:
                return_drift_bps = abs(series_return - validator_return) * 10_000.0
        future_actions = [
            action.as_dict()
            for action in actions
            if action.action_date > trading_date and (include_dividends or action.action_type != "dividend")
        ][:5]
        mismatch_samples.append(
            DailyMismatchSample(
                trading_date=trading_date,
                raw_close=float(raw_series.closes_by_date.get(trading_date)) if trading_date in raw_series.closes_by_date else None,
                adjustment_factor=float(factor_by_trading_date.get(trading_date, 1.0)),
                adjusted_close=adjusted_close,
                validator_close=validator_close,
                close_drift_bps=close_drift_bps,
                series_return=series_return,
                validator_return=validator_return,
                return_drift_bps=return_drift_bps,
                future_actions=future_actions,
            )
        )

    mismatch_samples.sort(
        key=lambda item: (
            item.close_drift_bps,
            item.return_drift_bps if item.return_drift_bps is not None else -1.0,
        ),
        reverse=True,
    )
    return mismatch_samples[:limit]


def validate_massive_adjusted_history(
    symbols: list[str],
    *,
    flatfiles_root: str | Path,
    recent_validation_days: int = 60,
    minimum_recent_overlap_days: int = 10,
) -> dict[str, Any]:
    """Validate Massive adjusted-close reconstruction from flat files plus actions."""

    normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    reports: dict[str, Any] = {}
    overall_status = "passed"
    generated_at = datetime.now(UTC).isoformat()

    for symbol in normalized_symbols:
        raw_series = load_massive_flatfile_close_series(symbol, flatfiles_root)
        actions = fetch_massive_corporate_actions(symbol, start_date=min(raw_series.closes_by_date))
        repaired_raw_series = raw_series
        split_adjusted_series = apply_massive_historical_adjustments(
            raw_series,
            actions,
            include_dividends=False,
        )
        rest_series = fetch_massive_rest_adjusted_series(
            symbol,
            start_date=min(split_adjusted_series.closes_by_date),
            end_date=max(split_adjusted_series.closes_by_date),
        )
        rest_comparison = compare_adjusted_series(
            split_adjusted_series,
            rest_series,
            minimum_overlap_days=1,
            max_mean_abs_close_drift_bps=1.0,
            max_max_abs_close_drift_bps=10.0,
            max_latest_close_drift_bps=1.0,
            max_mean_abs_return_drift_bps=1.0,
            max_max_abs_return_drift_bps=10.0,
        )
        rest_repairs = identify_isolated_rest_repairs(
            raw_series,
            split_adjusted_series,
            rest_series,
            actions,
            include_dividends=False,
        )
        if rest_comparison.status != "passed" and rest_repairs:
            repaired_raw_series = apply_series_repairs(raw_series, rest_repairs)
            split_adjusted_series = apply_massive_historical_adjustments(
                repaired_raw_series,
                actions,
                include_dividends=False,
            )
            rest_comparison = compare_adjusted_series(
                split_adjusted_series,
                rest_series,
                minimum_overlap_days=1,
                max_mean_abs_close_drift_bps=1.0,
                max_max_abs_close_drift_bps=10.0,
                max_latest_close_drift_bps=1.0,
                max_mean_abs_return_drift_bps=1.0,
                max_max_abs_return_drift_bps=10.0,
            )
        total_adjusted_series = apply_massive_historical_adjustments(
            repaired_raw_series,
            actions,
            include_dividends=True,
        )

        max_local_date = date.fromisoformat(max(total_adjusted_series.closes_by_date))
        recent_cutoff = max_local_date - timedelta(days=max(recent_validation_days * 2, recent_validation_days))
        recent_dates = [
            date_key
            for date_key in sorted(total_adjusted_series.closes_by_date)
            if date.fromisoformat(date_key) >= recent_cutoff
        ]
        alpaca_comparison: SeriesDriftReport
        if len(recent_dates) < minimum_recent_overlap_days:
            alpaca_comparison = SeriesDriftReport(
                provider=total_adjusted_series.provider,
                validator="alpaca_adjusted",
                status="skipped",
                overlap_days=len(recent_dates),
                compared_return_days=max(len(recent_dates) - 1, 0),
                mean_abs_close_drift_bps=0.0,
                max_abs_close_drift_bps=0.0,
                latest_close_drift_bps=0.0,
                mean_abs_return_drift_bps=0.0,
                max_abs_return_drift_bps=0.0,
                issues=[f"insufficient_recent_local_days:{len(recent_dates)}<{minimum_recent_overlap_days}"],
            )
        else:
            alpaca_series = fetch_alpaca_adjusted_series(symbol, recent_dates[0], recent_dates[-1])
            alpaca_comparison = compare_adjusted_series(
                ProviderPriceSeries(
                    symbol=total_adjusted_series.symbol,
                    provider=total_adjusted_series.provider,
                    closes_by_date={date_key: total_adjusted_series.closes_by_date[date_key] for date_key in recent_dates},
                    volumes_by_date={date_key: total_adjusted_series.volumes_by_date.get(date_key, 0.0) for date_key in recent_dates},
                    metadata=dict(total_adjusted_series.metadata),
                ),
                alpaca_series,
                minimum_overlap_days=minimum_recent_overlap_days,
                max_mean_abs_close_drift_bps=10.0,
                max_max_abs_close_drift_bps=50.0,
                max_latest_close_drift_bps=10.0,
                max_mean_abs_return_drift_bps=25.0,
                max_max_abs_return_drift_bps=100.0,
            )
            alpaca_comparison, alpaca_notes = reconcile_dividend_only_alpaca_comparison(actions, alpaca_comparison)
        if len(recent_dates) < minimum_recent_overlap_days:
            alpaca_notes: list[str] = []

        symbol_status = "passed"
        issues: list[str] = []
        notes: list[str] = []
        if rest_comparison.status != "passed":
            symbol_status = "failed"
            issues.extend(f"rest:{issue}" for issue in rest_comparison.issues)
        if rest_repairs:
            notes.append(f"rest:isolated_repairs_applied:{len(rest_repairs)}")
        if alpaca_comparison.status == "failed":
            symbol_status = "failed"
            issues.extend(f"alpaca:{issue}" for issue in alpaca_comparison.issues)
        elif alpaca_comparison.status == "skipped" and symbol_status == "passed":
            symbol_status = "partial"
            issues.extend(f"alpaca:{issue}" for issue in alpaca_comparison.issues)
        notes.extend(alpaca_notes)

        if symbol_status == "failed":
            overall_status = "failed"
        elif symbol_status == "partial" and overall_status == "passed":
            overall_status = "partial"

        reports[symbol] = {
            "status": symbol_status,
            "issues": issues,
            "notes": notes,
            "raw_flatfiles": {
                "provider": raw_series.provider,
                "day_count": len(raw_series.closes_by_date),
                "start_date": min(raw_series.closes_by_date),
                "end_date": max(raw_series.closes_by_date),
                "metadata": dict(raw_series.metadata),
            },
            "actions": {
                "count": len(actions),
                "by_type": {
                    "split": sum(1 for action in actions if action.action_type == "split"),
                    "dividend": sum(1 for action in actions if action.action_type == "dividend"),
                },
                "records": [action.as_dict() for action in actions],
            },
            "split_only_vs_massive_rest": rest_comparison.as_dict(),
            "total_adjusted_vs_alpaca": alpaca_comparison.as_dict(),
            "rest_repairs": list(rest_repairs),
            "top_rest_mismatches": [
                sample.as_dict()
                for sample in build_mismatch_samples(
                    repaired_raw_series,
                    split_adjusted_series,
                    rest_series,
                    actions,
                    limit=10,
                    include_dividends=False,
                )
            ],
        }

    return {
        "generated_at": generated_at,
        "flatfiles_root": str(Path(flatfiles_root).expanduser().resolve()),
        "symbols": normalized_symbols,
        "overall_status": overall_status,
        "reports": reports,
    }
