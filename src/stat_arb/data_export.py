"""Export stat-arb training price history from validated local provider stacks."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

from src.provider_adapters.alpaca_adapter import AlpacaMarketDataAdapter
from src.provider_adapters.alpha_vantage_adapter import AlphaVantageAdapter
from src.provider_adapters.base import ProviderError
from src.provider_adapters.polygon_adapter import MassiveAdapter


COMMON_DAILY_PATHS = (
    Path("equity/usa/daily"),
    Path("data/equity/usa/daily"),
)


@dataclass(frozen=True)
class SymbolPriceSeries:
    """Aligned daily closes discovered for one symbol."""

    symbol: str
    source_path: Path
    closes_by_date: dict[str, float]


@dataclass(frozen=True)
class ProviderPriceSeries:
    """Date-aware daily bar series loaded from a remote provider."""

    symbol: str
    provider: str
    closes_by_date: dict[str, float]
    volumes_by_date: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeriesQualityCheck:
    """Basic integrity checks for one symbol history."""

    day_count: int
    min_close: float
    max_close: float
    non_positive_close_count: int
    non_finite_close_count: int
    suspicious_return_count: int
    passed: bool
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "day_count": self.day_count,
            "min_close": round(self.min_close, 6),
            "max_close": round(self.max_close, 6),
            "non_positive_close_count": self.non_positive_close_count,
            "non_finite_close_count": self.non_finite_close_count,
            "suspicious_return_count": self.suspicious_return_count,
            "passed": self.passed,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class SeriesValidationResult:
    """Cross-provider validation stats for one symbol."""

    provider: str
    validator: str
    overlap_days: int
    compared_return_days: int
    mean_abs_return_drift_bps: float
    max_abs_return_drift_bps: float
    latest_close_drift_bps: float
    passed: bool
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "validator": self.validator,
            "overlap_days": self.overlap_days,
            "compared_return_days": self.compared_return_days,
            "mean_abs_return_drift_bps": round(self.mean_abs_return_drift_bps, 6),
            "max_abs_return_drift_bps": round(self.max_abs_return_drift_bps, 6),
            "latest_close_drift_bps": round(self.latest_close_drift_bps, 6),
            "passed": self.passed,
            "issues": list(self.issues),
        }


ProviderFetcher = Callable[[str, int], ProviderPriceSeries]


def _candidate_paths(root: Path, symbol: str) -> list[Path]:
    lowered = symbol.lower()
    paths: list[Path] = []
    for prefix in COMMON_DAILY_PATHS:
        paths.extend(
            [
                root / prefix / f"{lowered}.zip",
                root / prefix / f"{lowered}.csv",
                root / prefix / f"{symbol}.zip",
                root / prefix / f"{symbol}.csv",
            ]
        )
    paths.extend(
        [
            root / f"{lowered}.zip",
            root / f"{lowered}.csv",
            root / f"{symbol}.zip",
            root / f"{symbol}.csv",
        ]
    )
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def find_symbol_data_file(root: str | Path, symbol: str) -> Path:
    """Find the most likely LEAN daily data file for a symbol."""

    root_path = Path(root).expanduser().resolve()
    for candidate in _candidate_paths(root_path, symbol):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find LEAN daily data for {symbol} under {root_path}. "
        "Expected files like equity/usa/daily/<symbol>.zip"
    )


def _read_csv_rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError(f"{path} does not contain a CSV payload")
            member_name = sorted(csv_members)[0]
            payload = archive.read(member_name).decode("utf-8")
        handle = io.StringIO(payload)
    else:
        handle = path.open("r", encoding="utf-8")

    try:
        reader = csv.reader(handle)
        return [row for row in reader if row]
    finally:
        handle.close()


def _normalize_date(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    raise ValueError(f"Unable to parse trading date from value '{value}'")


def load_symbol_price_series(root: str | Path, symbol: str) -> SymbolPriceSeries:
    """Load daily close history for one symbol from LEAN-style CSV/ZIP data."""

    path = find_symbol_data_file(root, symbol)
    rows = _read_csv_rows(path)
    closes_by_date: dict[str, float] = {}
    for row in rows:
        if len(row) < 5:
            continue
        raw_date = row[0].strip()
        if not raw_date:
            continue
        try:
            trading_date = _normalize_date(raw_date)
            close = float(row[4])
        except ValueError:
            continue
        closes_by_date[trading_date] = close
    if len(closes_by_date) < 10:
        raise ValueError(f"{path} does not contain enough daily bars for {symbol}")
    return SymbolPriceSeries(
        symbol=symbol.upper(),
        source_path=path,
        closes_by_date=closes_by_date,
    )


def export_aligned_price_history(
    root: str | Path,
    symbols: list[str],
    *,
    minimum_common_days: int = 60,
) -> dict[str, object]:
    """Export aligned calendar + closes across the requested symbols from LEAN files."""

    if len(symbols) < 2:
        raise ValueError("At least two symbols are required to export stat-arb training history")
    series = [load_symbol_price_series(root, symbol) for symbol in symbols]
    common_dates = set(series[0].closes_by_date)
    for item in series[1:]:
        common_dates &= set(item.closes_by_date)
    aligned_dates = sorted(common_dates)
    if len(aligned_dates) < minimum_common_days:
        raise ValueError(
            f"Only {len(aligned_dates)} common daily bars were found across the requested universe; "
            f"at least {minimum_common_days} are required"
        )

    return {
        "calendar": aligned_dates,
        "price_history": {
            item.symbol: [item.closes_by_date[date] for date in aligned_dates]
            for item in series
        },
        "metadata": {
            "export_mode": "lean_local",
            "symbols": [item.symbol for item in series],
            "source_paths": {item.symbol: str(item.source_path) for item in series},
            "common_days": len(aligned_dates),
        },
    }


def write_price_history_json(payload: dict[str, object], output_path: str | Path) -> Path:
    """Persist aligned price history to the trainer input format."""

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _timestamp_to_trading_date(timestamp: float) -> str:
    value = float(timestamp)
    if value > 1_000_000_000_000:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=UTC).date().isoformat()


def _fetch_massive_price_series(symbol: str, lookback_days: int) -> ProviderPriceSeries:
    adapter = MassiveAdapter()
    end = datetime.now(UTC).date()
    start = end.fromordinal(end.toordinal() - max(lookback_days * 3, lookback_days + 30))
    next_target: str | None = adapter._build_aggregates_path(symbol, start.isoformat(), end.isoformat())
    request_params: dict[str, Any] | None = {
        "adjusted": "true",
        "sort": "asc",
        "limit": min(max(lookback_days * 4, 5000), 50000),
    }
    parsed_results: list[dict[str, float]] = []
    seen_urls: set[str] = set()

    while next_target:
        if next_target in seen_urls:
            raise ProviderError("Massive aggregates pagination returned a repeated next_url")
        seen_urls.add(next_target)
        payload = adapter._request(next_target, params=request_params)
        parsed_results.extend(adapter._parse_aggregate_payload(payload))
        next_target = payload.get("next_url")
        request_params = None

    parsed_results = parsed_results[-lookback_days:]
    if len(parsed_results) < lookback_days:
        raise ProviderError(
            f"Insufficient Massive daily bars returned for {symbol}: required={lookback_days} received={len(parsed_results)}"
        )
    closes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["close"]) for item in parsed_results}
    volumes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["volume"]) for item in parsed_results}
    return ProviderPriceSeries(
        symbol=symbol.upper(),
        provider="massive",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "adjusted": True,
            "base_url": adapter.base_url,
            "path_template": adapter.aggregates_path_template,
            "requested_lookback_days": lookback_days,
        },
    )


def _fetch_alpaca_price_series(symbol: str, lookback_days: int) -> ProviderPriceSeries:
    adapter = AlpacaMarketDataAdapter()
    end_at = datetime.now(UTC)
    start_at = end_at - timedelta(days=max(lookback_days * 3, lookback_days + 45))
    payload = adapter._request(
        adapter.bars_path_template.format(symbol=symbol),
        params={
            "timeframe": "1Day",
            "limit": max(lookback_days * 2, 1000),
            "adjustment": "all",
            "feed": adapter.feed,
            "sort": "asc",
            "start": start_at.isoformat().replace("+00:00", "Z"),
            "end": end_at.isoformat().replace("+00:00", "Z"),
        },
    )
    normalized = adapter._normalize_bar_payload(payload)[-lookback_days:]
    if len(normalized) < lookback_days:
        raise ProviderError(
            f"Insufficient Alpaca daily bars returned for {symbol}: required={lookback_days} received={len(normalized)}"
        )
    closes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["close"]) for item in normalized}
    volumes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["volume"]) for item in normalized}
    return ProviderPriceSeries(
        symbol=symbol.upper(),
        provider="alpaca",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "adjusted": True,
            "feed": adapter.feed,
            "base_url": adapter.market_data_base_url,
            "requested_lookback_days": lookback_days,
        },
    )


def _fetch_alpha_vantage_price_series(symbol: str, lookback_days: int) -> ProviderPriceSeries:
    adapter = AlphaVantageAdapter()
    payload = adapter._request(
        {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": "full",
        }
    )
    normalized = adapter._normalize_daily_adjusted_payload(payload)[-lookback_days:]
    if len(normalized) < lookback_days:
        raise ProviderError(
            f"Insufficient Alpha Vantage daily bars returned for {symbol}: required={lookback_days} received={len(normalized)}"
        )
    closes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["close"]) for item in normalized}
    volumes_by_date = {_timestamp_to_trading_date(item["timestamp"]): float(item["volume"]) for item in normalized}
    return ProviderPriceSeries(
        symbol=symbol.upper(),
        provider="alpha_vantage",
        closes_by_date=closes_by_date,
        volumes_by_date=volumes_by_date,
        metadata={
            "adjusted": True,
            "base_url": adapter.base_url,
            "requested_lookback_days": lookback_days,
        },
    )


PROVIDER_FETCHERS: dict[str, ProviderFetcher] = {
    "massive": _fetch_massive_price_series,
    "alpaca": _fetch_alpaca_price_series,
    "alpha_vantage": _fetch_alpha_vantage_price_series,
}


def _safe_log_return(current: float, previous: float) -> float | None:
    if current <= 0.0 or previous <= 0.0:
        return None
    return math.log(current / previous)


def run_series_quality_check(
    series: ProviderPriceSeries,
    *,
    minimum_history_days: int,
    suspicious_return_threshold: float = 0.40,
) -> SeriesQualityCheck:
    """Reject obviously broken price histories before model training."""

    ordered_dates = sorted(series.closes_by_date)
    closes = [float(series.closes_by_date[date]) for date in ordered_dates]
    issues: list[str] = []
    non_positive_close_count = sum(1 for value in closes if value <= 0.0)
    non_finite_close_count = sum(1 for value in closes if not math.isfinite(value))
    suspicious_return_count = 0
    previous_close: float | None = None
    for close in closes:
        if previous_close is not None:
            log_return = _safe_log_return(close, previous_close)
            if log_return is None:
                suspicious_return_count += 1
            elif abs(log_return) > suspicious_return_threshold:
                suspicious_return_count += 1
        previous_close = close

    if len(closes) < minimum_history_days:
        issues.append(f"history_too_short:{len(closes)}<{minimum_history_days}")
    if non_positive_close_count:
        issues.append(f"non_positive_closes:{non_positive_close_count}")
    if non_finite_close_count:
        issues.append(f"non_finite_closes:{non_finite_close_count}")

    passed = not issues
    return SeriesQualityCheck(
        day_count=len(closes),
        min_close=min(closes) if closes else 0.0,
        max_close=max(closes) if closes else 0.0,
        non_positive_close_count=non_positive_close_count,
        non_finite_close_count=non_finite_close_count,
        suspicious_return_count=suspicious_return_count,
        passed=passed,
        issues=issues,
    )


def compare_series_against_validator(
    series: ProviderPriceSeries,
    validator: ProviderPriceSeries,
    *,
    validation_window_days: int,
    minimum_overlap_days: int,
    max_mean_abs_return_drift_bps: float,
    max_max_abs_return_drift_bps: float,
    max_latest_close_drift_bps: float,
) -> SeriesValidationResult:
    """Compare recent adjusted history against the validation source."""

    overlap_dates = sorted(set(series.closes_by_date) & set(validator.closes_by_date))
    overlap_dates = overlap_dates[-validation_window_days:]
    issues: list[str] = []
    if len(overlap_dates) < minimum_overlap_days:
        issues.append(f"insufficient_overlap:{len(overlap_dates)}<{minimum_overlap_days}")
        return SeriesValidationResult(
            provider=series.provider,
            validator=validator.provider,
            overlap_days=len(overlap_dates),
            compared_return_days=max(len(overlap_dates) - 1, 0),
            mean_abs_return_drift_bps=0.0,
            max_abs_return_drift_bps=0.0,
            latest_close_drift_bps=0.0,
            passed=False,
            issues=issues,
        )

    ordered_series = [float(series.closes_by_date[date]) for date in overlap_dates]
    ordered_validator = [float(validator.closes_by_date[date]) for date in overlap_dates]
    drift_bps: list[float] = []
    for index in range(1, len(overlap_dates)):
        series_return = _safe_log_return(ordered_series[index], ordered_series[index - 1])
        validator_return = _safe_log_return(ordered_validator[index], ordered_validator[index - 1])
        if series_return is None or validator_return is None:
            continue
        drift_bps.append(abs(series_return - validator_return) * 10_000.0)

    latest_close = ordered_series[-1]
    latest_validator_close = ordered_validator[-1]
    latest_close_drift_bps = (
        abs(latest_close - latest_validator_close) / max(abs(latest_validator_close), 1e-9) * 10_000.0
    )
    mean_abs_return_drift_bps = sum(drift_bps) / len(drift_bps) if drift_bps else 0.0
    max_abs_return_drift_bps = max(drift_bps) if drift_bps else 0.0

    if mean_abs_return_drift_bps > max_mean_abs_return_drift_bps:
        issues.append(
            f"mean_return_drift_bps:{mean_abs_return_drift_bps:.4f}>{max_mean_abs_return_drift_bps:.4f}"
        )
    if max_abs_return_drift_bps > max_max_abs_return_drift_bps:
        issues.append(f"max_return_drift_bps:{max_abs_return_drift_bps:.4f}>{max_max_abs_return_drift_bps:.4f}")
    if latest_close_drift_bps > max_latest_close_drift_bps:
        issues.append(f"latest_close_drift_bps:{latest_close_drift_bps:.4f}>{max_latest_close_drift_bps:.4f}")

    return SeriesValidationResult(
        provider=series.provider,
        validator=validator.provider,
        overlap_days=len(overlap_dates),
        compared_return_days=max(len(drift_bps), 0),
        mean_abs_return_drift_bps=mean_abs_return_drift_bps,
        max_abs_return_drift_bps=max_abs_return_drift_bps,
        latest_close_drift_bps=latest_close_drift_bps,
        passed=not issues,
        issues=issues,
    )


def _fetch_series(fetcher_name: str, symbol: str, lookback_days: int) -> ProviderPriceSeries:
    if fetcher_name not in PROVIDER_FETCHERS:
        raise ValueError(f"Unsupported provider fetcher: {fetcher_name}")
    return PROVIDER_FETCHERS[fetcher_name](symbol, lookback_days)


def _series_summary(series: ProviderPriceSeries, quality: SeriesQualityCheck) -> dict[str, Any]:
    ordered_dates = sorted(series.closes_by_date)
    return {
        "provider": series.provider,
        "symbol": series.symbol,
        "date_range": {
            "start": ordered_dates[0] if ordered_dates else None,
            "end": ordered_dates[-1] if ordered_dates else None,
        },
        "quality": quality.as_dict(),
        "metadata": dict(series.metadata),
    }


def export_provider_validated_price_history(
    symbols: list[str],
    *,
    lookback_days: int,
    minimum_history_days: int,
    minimum_common_days: int,
    primary_provider: str = "massive",
    validator_provider: str = "alpaca",
    repair_provider: str = "alpha_vantage",
    validation_window_days: int = 60,
    minimum_validator_overlap_days: int = 30,
    max_mean_abs_return_drift_bps: float = 75.0,
    max_max_abs_return_drift_bps: float = 500.0,
    max_latest_close_drift_bps: float = 250.0,
) -> dict[str, object]:
    """Export aligned daily history from provider-backed validated series.

    The policy is intentionally conservative:

    - primary source: Massive
    - validator source: Alpaca
    - full-history repair source: Alpha Vantage

    Each chosen series must pass internal integrity checks and recent-window
    validator drift checks before it is admitted to the training payload.
    """

    if len(symbols) < 2:
        raise ValueError("At least two symbols are required to export stat-arb training history")

    chosen_series: list[ProviderPriceSeries] = []
    symbol_provenance: dict[str, Any] = {}
    excluded_symbols: dict[str, Any] = {}

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue

        attempts: dict[str, Any] = {}
        try:
            primary = _fetch_series(primary_provider, symbol, lookback_days)
            primary_quality = run_series_quality_check(primary, minimum_history_days=minimum_history_days)
            attempts["primary"] = _series_summary(primary, primary_quality)
        except Exception as exc:
            excluded_symbols[symbol] = {
                "reason": "primary_fetch_failed",
                "error": str(exc),
                "providers": {"primary": primary_provider, "validator": validator_provider, "repair": repair_provider},
            }
            continue

        validator_error: str | None = None
        validator: ProviderPriceSeries | None = None
        try:
            validator = _fetch_series(validator_provider, symbol, lookback_days)
            validator_quality = run_series_quality_check(validator, minimum_history_days=minimum_history_days)
            attempts["validator"] = _series_summary(validator, validator_quality)
        except Exception as exc:
            validator_error = str(exc)

        primary_validation: SeriesValidationResult | None = None
        if validator is not None and attempts["primary"]["quality"]["passed"] and attempts["validator"]["quality"]["passed"]:
            primary_validation = compare_series_against_validator(
                primary,
                validator,
                validation_window_days=validation_window_days,
                minimum_overlap_days=minimum_validator_overlap_days,
                max_mean_abs_return_drift_bps=max_mean_abs_return_drift_bps,
                max_max_abs_return_drift_bps=max_max_abs_return_drift_bps,
                max_latest_close_drift_bps=max_latest_close_drift_bps,
            )

        chosen: ProviderPriceSeries | None = None
        chosen_reason: str | None = None

        if attempts["primary"]["quality"]["passed"] and primary_validation and primary_validation.passed:
            chosen = primary
            chosen_reason = "primary_validated"

        repair_validation: SeriesValidationResult | None = None
        if chosen is None:
            try:
                repair = _fetch_series(repair_provider, symbol, lookback_days)
                repair_quality = run_series_quality_check(repair, minimum_history_days=minimum_history_days)
                attempts["repair"] = _series_summary(repair, repair_quality)
                if repair_quality.passed and validator is not None and attempts["validator"]["quality"]["passed"]:
                    repair_validation = compare_series_against_validator(
                        repair,
                        validator,
                        validation_window_days=validation_window_days,
                        minimum_overlap_days=minimum_validator_overlap_days,
                        max_mean_abs_return_drift_bps=max_mean_abs_return_drift_bps,
                        max_max_abs_return_drift_bps=max_max_abs_return_drift_bps,
                        max_latest_close_drift_bps=max_latest_close_drift_bps,
                    )
                if repair_quality.passed and repair_validation and repair_validation.passed:
                    chosen = repair
                    chosen_reason = "repair_validated"
            except Exception as exc:
                attempts["repair"] = {"provider": repair_provider, "error": str(exc)}

        if chosen is None:
            excluded_symbols[symbol] = {
                "reason": "no_validated_series",
                "providers": {"primary": primary_provider, "validator": validator_provider, "repair": repair_provider},
                "validator_error": validator_error,
                "attempts": {
                    **attempts,
                    "primary_validation": primary_validation.as_dict() if primary_validation else None,
                    "repair_validation": repair_validation.as_dict() if repair_validation else None,
                },
            }
            continue

        chosen_series.append(chosen)
        symbol_provenance[symbol] = {
            "chosen_provider": chosen.provider,
            "chosen_reason": chosen_reason,
            "providers": {"primary": primary_provider, "validator": validator_provider, "repair": repair_provider},
            "validator_error": validator_error,
            "attempts": {
                **attempts,
                "primary_validation": primary_validation.as_dict() if primary_validation else None,
                "repair_validation": repair_validation.as_dict() if repair_validation else None,
            },
        }

    if len(chosen_series) < 2:
        raise ValueError(
            "Provider-backed export produced fewer than two validated symbols. "
            f"validated={len(chosen_series)} excluded={len(excluded_symbols)}"
        )

    common_dates = set(chosen_series[0].closes_by_date)
    for item in chosen_series[1:]:
        common_dates &= set(item.closes_by_date)
    aligned_dates = sorted(common_dates)
    if len(aligned_dates) < minimum_common_days:
        raise ValueError(
            f"Only {len(aligned_dates)} common validated daily bars were found across the requested universe; "
            f"at least {minimum_common_days} are required"
        )

    return {
        "calendar": aligned_dates,
        "price_history": {
            item.symbol: [item.closes_by_date[date] for date in aligned_dates]
            for item in chosen_series
        },
        "metadata": {
            "export_mode": "provider_validated",
            "provider_policy": {
                "primary": primary_provider,
                "validator": validator_provider,
                "repair": repair_provider,
                "validation_window_days": validation_window_days,
                "minimum_validator_overlap_days": minimum_validator_overlap_days,
                "max_mean_abs_return_drift_bps": max_mean_abs_return_drift_bps,
                "max_max_abs_return_drift_bps": max_max_abs_return_drift_bps,
                "max_latest_close_drift_bps": max_latest_close_drift_bps,
            },
            "symbols_requested": [symbol.strip().upper() for symbol in symbols if symbol.strip()],
            "symbols_included": [item.symbol for item in chosen_series],
            "symbols_excluded": excluded_symbols,
            "common_days": len(aligned_dates),
            "symbol_provenance": symbol_provenance,
        },
    }
