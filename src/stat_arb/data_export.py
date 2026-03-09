"""Export stat-arb training price history from validated local provider stacks."""

from __future__ import annotations

import csv
import io
import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

import requests

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
ProgressCallback = Callable[[str], None]
PROGRESS_CALLBACK: ProgressCallback | None = None


class ProviderExportError(ValueError):
    """Raised when provider-backed training export cannot produce a safe dataset."""

    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def set_progress_callback(callback: ProgressCallback | None) -> None:
    """Install or clear the exporter progress callback."""

    global PROGRESS_CALLBACK
    PROGRESS_CALLBACK = callback


def _emit_progress(message: str) -> None:
    if PROGRESS_CALLBACK is not None:
        PROGRESS_CALLBACK(message)


def _format_progress(prefix: str, *, symbol: str | None = None, detail: str | None = None) -> str:
    parts = [prefix]
    if symbol:
        parts.append(symbol)
    if detail:
        parts.append(detail)
    return " | ".join(parts)


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


def export_massive_flatfiles_price_history(
    symbols: list[str],
    *,
    flatfiles_root: str | Path,
    minimum_common_days: int,
    recent_validation_days: int = 60,
    minimum_recent_overlap_days: int = 10,
    validation_report: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Export aligned total-adjusted closes from Massive flat files after validation."""

    from src.stat_arb.massive_validation import (
        apply_massive_historical_adjustments,
        apply_series_repairs,
        fetch_massive_corporate_actions,
        load_massive_flatfile_close_series,
        validate_massive_adjusted_history,
    )

    if len(symbols) < 2:
        raise ValueError("At least two symbols are required to export stat-arb training history")

    normalized_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if validation_report is None:
        validation_report = validate_massive_adjusted_history(
            normalized_symbols,
            flatfiles_root=flatfiles_root,
            recent_validation_days=recent_validation_days,
            minimum_recent_overlap_days=minimum_recent_overlap_days,
        )
    report_symbols = validation_report.get("reports", {})
    for symbol in normalized_symbols:
        symbol_report = report_symbols.get(symbol)
        if symbol_report is None:
            raise ProviderExportError(
                f"Massive flat-file validation report is missing symbol {symbol}",
                diagnostics=validation_report,
            )
        if symbol_report.get("status") != "passed":
            raise ProviderExportError(
                f"Massive flat-file validation report must mark {symbol} as passed before export",
                diagnostics=validation_report,
            )

    adjusted_series: list[ProviderPriceSeries] = []
    symbol_provenance: dict[str, Any] = {}
    for symbol in normalized_symbols:
        symbol_report = validation_report["reports"][symbol]
        raw_series = load_massive_flatfile_close_series(symbol, flatfiles_root)
        raw_series = apply_series_repairs(raw_series, symbol_report.get("rest_repairs", []))
        actions = fetch_massive_corporate_actions(symbol, start_date=min(raw_series.closes_by_date))
        total_adjusted_series = apply_massive_historical_adjustments(
            raw_series,
            actions,
            include_dividends=True,
        )
        adjusted_series.append(total_adjusted_series)
        symbol_provenance[symbol] = {
            "chosen_provider": "massive_flatfiles_total_adjusted",
            "chosen_reason": "validated_massive_flatfiles",
            "raw_day_count": len(raw_series.closes_by_date),
            "adjusted_day_count": len(total_adjusted_series.closes_by_date),
            "action_count": len(actions),
            "split_count": sum(1 for action in actions if action.action_type == "split"),
            "dividend_count": sum(1 for action in actions if action.action_type == "dividend"),
            "validation_status": validation_report["reports"][symbol]["status"],
            "rest_repair_count": len(symbol_report.get("rest_repairs", [])),
        }

    common_dates = set(adjusted_series[0].closes_by_date)
    for series in adjusted_series[1:]:
        common_dates &= set(series.closes_by_date)
    aligned_dates = sorted(common_dates)
    if len(aligned_dates) < minimum_common_days:
        raise ProviderExportError(
            f"Only {len(aligned_dates)} common daily bars were found across the Massive flat-file universe; "
            f"at least {minimum_common_days} are required",
            diagnostics={
                "export_mode": "massive_flatfiles_validated",
                "symbols_requested": normalized_symbols,
                "symbols_included": [series.symbol for series in adjusted_series],
                "common_days": len(aligned_dates),
                "validation_report": validation_report,
            },
        )

    return {
        "calendar": aligned_dates,
        "price_history": {
            series.symbol: [series.closes_by_date[date] for date in aligned_dates]
            for series in adjusted_series
        },
        "metadata": {
            "export_mode": "massive_flatfiles_validated",
            "symbols": [series.symbol for series in adjusted_series],
            "symbols_included": [series.symbol for series in adjusted_series],
            "common_days": len(aligned_dates),
            "flatfiles_root": str(Path(flatfiles_root).expanduser().resolve()),
            "symbol_provenance": symbol_provenance,
            "validation_report": validation_report,
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
    # Massive appears to cap some accounts at 500 aggregate rows per request even
    # when higher limits are requested. Fetch roughly one trading year at a time,
    # then reassemble locally to reduce truncation before falling through.
    chunk_calendar_days = 365
    current_end = datetime.now(UTC).date()
    earliest_start = current_end.fromordinal(current_end.toordinal() - max(lookback_days * 4, lookback_days + 365))
    bars_by_date: dict[str, dict[str, float]] = {}
    request_count = 0
    chunk_count = 0
    _emit_progress(_format_progress("provider=massive start", symbol=symbol, detail=f"lookback_days={lookback_days}"))

    while current_end >= earliest_start and len(bars_by_date) < lookback_days:
        chunk_count += 1
        chunk_start = max(earliest_start, current_end.fromordinal(current_end.toordinal() - chunk_calendar_days))
        _emit_progress(
            _format_progress(
                "provider=massive chunk",
                symbol=symbol,
                detail=f"{chunk_count} range={chunk_start.isoformat()}..{current_end.isoformat()} current_bars={len(bars_by_date)}",
            )
        )
        next_target: str | None = adapter._build_aggregates_path(symbol, chunk_start.isoformat(), current_end.isoformat())
        request_params: dict[str, Any] | None = {
            "adjusted": "true",
            "sort": "asc",
            # Keep this at 500 because many lower-tier accounts appear capped there anyway.
            "limit": 500,
        }
        seen_urls: set[str] = set()

        while next_target:
            if next_target in seen_urls:
                raise ProviderError("Massive aggregates pagination returned a repeated next_url")
            seen_urls.add(next_target)
            payload = _request_massive_payload_with_backoff(adapter, next_target, params=request_params)
            request_count += 1
            for item in adapter._parse_aggregate_payload(payload):
                trading_date = _timestamp_to_trading_date(item["timestamp"])
                bars_by_date[trading_date] = item
            _emit_progress(
                _format_progress(
                    "provider=massive page",
                    symbol=symbol,
                    detail=f"requests={request_count} bars={len(bars_by_date)}",
                )
            )
            next_target = payload.get("next_url")
            request_params = None

        # Small pacing delay between chunk windows to reduce rate-limit bursts.
        time.sleep(0.2)
        current_end = chunk_start - timedelta(days=1)

    ordered_dates = sorted(bars_by_date)
    parsed_results = [bars_by_date[date] for date in ordered_dates][-lookback_days:]
    if len(parsed_results) < lookback_days:
        raise ProviderError(
            f"Insufficient Massive daily bars returned for {symbol}: required={lookback_days} received={len(parsed_results)}"
        )
    _emit_progress(
        _format_progress(
            "provider=massive done",
            symbol=symbol,
            detail=f"bars={len(parsed_results)} requests={request_count} chunks={chunk_count}",
        )
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
            "chunk_calendar_days": chunk_calendar_days,
            "request_count": request_count,
            "chunk_count": chunk_count,
        },
    )


def _fetch_alpaca_price_series(symbol: str, lookback_days: int) -> ProviderPriceSeries:
    adapter = AlpacaMarketDataAdapter()
    _emit_progress(_format_progress("provider=alpaca start", symbol=symbol, detail=f"lookback_days={lookback_days}"))
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
    _emit_progress(_format_progress("provider=alpaca done", symbol=symbol, detail=f"bars={len(normalized)}"))
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
    _emit_progress(
        _format_progress("provider=alpha_vantage start", symbol=symbol, detail=f"lookback_days={lookback_days}")
    )
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
    _emit_progress(_format_progress("provider=alpha_vantage done", symbol=symbol, detail=f"bars={len(normalized)}"))
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


def _request_massive_payload_with_backoff(
    adapter: MassiveAdapter,
    path_or_url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = 5,
    initial_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Issue one Massive request with explicit 429 handling and bounded retries."""

    if not adapter.api_key:
        raise ProviderError("MASSIVE_API_KEY is not configured (POLYGON_API_KEY is also accepted for compatibility)")

    url, payload = adapter._prepare_url_and_params(path_or_url, params=params)
    delay_seconds = initial_delay_seconds
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        try:
            response = adapter.session.get(
                url,
                params=payload,
                headers={"Authorization": f"Bearer {adapter.api_key}"},
                timeout=adapter.timeout_seconds,
            )
        except requests.Timeout as exc:
            last_error = f"Massive request timed out for {url}"
            if attempt == max_retries:
                raise ProviderError(
                    f"Massive request failed after {max_retries + 1} attempts due to timeout: {url}"
                ) from exc
            _emit_progress(
                _format_progress(
                    "provider=massive timeout",
                    detail=f"attempt={attempt + 1}/{max_retries + 1} wait={delay_seconds:.1f}s",
                )
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2.0, 30.0)
            continue
        except requests.RequestException as exc:
            last_error = f"Massive request transport failed for {url}: {exc}"
            if attempt == max_retries:
                raise ProviderError(
                    f"Massive request failed after {max_retries + 1} attempts due to transport error: {url}"
                ) from exc
            _emit_progress(
                _format_progress(
                    "provider=massive transport_error",
                    detail=f"attempt={attempt + 1}/{max_retries + 1} wait={delay_seconds:.1f}s",
                )
            )
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2.0, 30.0)
            continue
        if response.status_code == 429:
            last_error = f"Massive request rate-limited for {url}"
            if attempt == max_retries:
                raise ProviderError(
                    f"Massive request failed after {max_retries + 1} attempts due to rate limiting: {url}"
                )
            retry_after_header = response.headers.get("Retry-After")
            try:
                retry_after_seconds = float(retry_after_header) if retry_after_header is not None else delay_seconds
            except ValueError:
                retry_after_seconds = delay_seconds
            _emit_progress(
                _format_progress(
                    "provider=massive rate_limited",
                    detail=f"attempt={attempt + 1}/{max_retries + 1} wait={max(retry_after_seconds, 0.0):.1f}s",
                )
            )
            time.sleep(max(retry_after_seconds, 0.0))
            delay_seconds = min(delay_seconds * 2.0, 30.0)
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Massive request failed: {exc}") from exc
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise ProviderError(f"Massive response was not valid JSON: {exc}") from exc

    raise ProviderError(last_error or f"Massive request failed unexpectedly: {url}")


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


def _build_provider_export_diagnostics(
    *,
    symbols_requested: list[str],
    symbols_included: list[str],
    excluded_symbols: dict[str, Any],
    provider_policy: dict[str, Any],
    common_days: int | None = None,
) -> dict[str, Any]:
    return {
        "export_mode": "provider_validated",
        "symbols_requested": symbols_requested,
        "symbols_included": symbols_included,
        "symbols_excluded": excluded_symbols,
        "provider_policy": provider_policy,
        "common_days": common_days,
    }


def _summarize_excluded_symbols(excluded_symbols: dict[str, Any], limit: int = 3) -> str:
    fragments: list[str] = []
    for symbol in sorted(excluded_symbols)[:limit]:
        record = excluded_symbols[symbol]
        reason = record.get("reason", "unknown")
        if reason == "primary_fetch_failed":
            fragments.append(f"{symbol}:primary_fetch_failed:{record.get('error', 'unknown')}")
            continue
        attempts = record.get("attempts", {})
        primary_validation = attempts.get("primary_validation") or {}
        repair_validation = attempts.get("repair_validation") or {}
        validator_error = record.get("validator_error")
        if primary_validation.get("issues"):
            fragments.append(f"{symbol}:primary_validation:{','.join(primary_validation['issues'])}")
        elif repair_validation.get("issues"):
            fragments.append(f"{symbol}:repair_validation:{','.join(repair_validation['issues'])}")
        elif validator_error:
            fragments.append(f"{symbol}:validator:{validator_error}")
        else:
            fragments.append(f"{symbol}:{reason}")
    return " | ".join(fragments)


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

    requested_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    provider_policy = {
        "primary": primary_provider,
        "validator": validator_provider,
        "repair": repair_provider,
        "validation_window_days": validation_window_days,
        "minimum_validator_overlap_days": minimum_validator_overlap_days,
        "max_mean_abs_return_drift_bps": max_mean_abs_return_drift_bps,
        "max_max_abs_return_drift_bps": max_max_abs_return_drift_bps,
        "max_latest_close_drift_bps": max_latest_close_drift_bps,
    }

    chosen_series: list[ProviderPriceSeries] = []
    symbol_provenance: dict[str, Any] = {}
    excluded_symbols: dict[str, Any] = {}

    for raw_symbol in requested_symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        current_index = len(chosen_series) + len(excluded_symbols) + 1
        _emit_progress(
            _format_progress(
                f"[{current_index}/{len(requested_symbols)}] symbol_start",
                symbol=symbol,
                detail=f"primary={primary_provider} validator={validator_provider} repair={repair_provider}",
            )
        )

        attempts: dict[str, Any] = {}
        primary: ProviderPriceSeries | None = None
        primary_quality: SeriesQualityCheck | None = None
        try:
            primary = _fetch_series(primary_provider, symbol, lookback_days)
            primary_quality = run_series_quality_check(primary, minimum_history_days=minimum_history_days)
            attempts["primary"] = _series_summary(primary, primary_quality)
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] primary_ok",
                    symbol=symbol,
                    detail=f"days={primary_quality.day_count}",
                )
            )
        except Exception as exc:
            attempts["primary"] = {
                "provider": primary_provider,
                "error": str(exc),
            }
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] primary_failed",
                    symbol=symbol,
                    detail=str(exc),
                )
            )

        validator_error: str | None = None
        validator: ProviderPriceSeries | None = None
        try:
            validator = _fetch_series(validator_provider, symbol, lookback_days)
            validator_quality = run_series_quality_check(validator, minimum_history_days=minimum_history_days)
            attempts["validator"] = _series_summary(validator, validator_quality)
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] validator_ok",
                    symbol=symbol,
                    detail=f"days={validator_quality.day_count}",
                )
            )
        except Exception as exc:
            validator_error = str(exc)
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] validator_failed",
                    symbol=symbol,
                    detail=validator_error,
                )
            )

        primary_validation: SeriesValidationResult | None = None
        if (
            primary is not None
            and primary_quality is not None
            and validator is not None
            and primary_quality.passed
            and attempts["validator"]["quality"]["passed"]
        ):
            primary_validation = compare_series_against_validator(
                primary,
                validator,
                validation_window_days=validation_window_days,
                minimum_overlap_days=minimum_validator_overlap_days,
                max_mean_abs_return_drift_bps=max_mean_abs_return_drift_bps,
                max_max_abs_return_drift_bps=max_max_abs_return_drift_bps,
                max_latest_close_drift_bps=max_latest_close_drift_bps,
            )
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] primary_validation",
                    symbol=symbol,
                    detail=f"passed={primary_validation.passed} overlap={primary_validation.overlap_days}",
                )
            )

        chosen: ProviderPriceSeries | None = None
        chosen_reason: str | None = None

        if primary is not None and primary_quality is not None and primary_quality.passed and primary_validation and primary_validation.passed:
            chosen = primary
            chosen_reason = "primary_validated"

        repair_validation: SeriesValidationResult | None = None
        if chosen is None:
            try:
                repair = _fetch_series(repair_provider, symbol, lookback_days)
                repair_quality = run_series_quality_check(repair, minimum_history_days=minimum_history_days)
                attempts["repair"] = _series_summary(repair, repair_quality)
                _emit_progress(
                    _format_progress(
                        f"[{current_index}/{len(requested_symbols)}] repair_ok",
                        symbol=symbol,
                        detail=f"days={repair_quality.day_count}",
                    )
                )
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
                    _emit_progress(
                        _format_progress(
                            f"[{current_index}/{len(requested_symbols)}] repair_validation",
                            symbol=symbol,
                            detail=f"passed={repair_validation.passed} overlap={repair_validation.overlap_days}",
                        )
                    )
                if repair_quality.passed and repair_validation and repair_validation.passed:
                    chosen = repair
                    chosen_reason = "repair_validated"
            except Exception as exc:
                attempts["repair"] = {"provider": repair_provider, "error": str(exc)}
                _emit_progress(
                    _format_progress(
                        f"[{current_index}/{len(requested_symbols)}] repair_failed",
                        symbol=symbol,
                        detail=str(exc),
                    )
                )

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
            _emit_progress(
                _format_progress(
                    f"[{current_index}/{len(requested_symbols)}] symbol_excluded",
                    symbol=symbol,
                    detail="no_validated_series",
                )
            )
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
        _emit_progress(
            _format_progress(
                f"[{current_index}/{len(requested_symbols)}] symbol_selected",
                symbol=symbol,
                detail=f"provider={chosen.provider} reason={chosen_reason}",
            )
        )

    if len(chosen_series) < 2:
        diagnostics = _build_provider_export_diagnostics(
            symbols_requested=requested_symbols,
            symbols_included=[item.symbol for item in chosen_series],
            excluded_symbols=excluded_symbols,
            provider_policy=provider_policy,
        )
        raise ProviderExportError(
            "Provider-backed export produced fewer than two validated symbols. "
            f"validated={len(chosen_series)} excluded={len(excluded_symbols)}"
            + (f" | sample={_summarize_excluded_symbols(excluded_symbols)}" if excluded_symbols else ""),
            diagnostics=diagnostics,
        )

    common_dates = set(chosen_series[0].closes_by_date)
    for item in chosen_series[1:]:
        common_dates &= set(item.closes_by_date)
    aligned_dates = sorted(common_dates)
    if len(aligned_dates) < minimum_common_days:
        diagnostics = _build_provider_export_diagnostics(
            symbols_requested=requested_symbols,
            symbols_included=[item.symbol for item in chosen_series],
            excluded_symbols=excluded_symbols,
            provider_policy=provider_policy,
            common_days=len(aligned_dates),
        )
        raise ProviderExportError(
            f"Only {len(aligned_dates)} common validated daily bars were found across the requested universe; "
            f"at least {minimum_common_days} are required",
            diagnostics=diagnostics,
        )

    return {
        "calendar": aligned_dates,
        "price_history": {
            item.symbol: [item.closes_by_date[date] for date in aligned_dates]
            for item in chosen_series
        },
        "metadata": {
            "export_mode": "provider_validated",
            "provider_policy": provider_policy,
            "symbols_requested": requested_symbols,
            "symbols_included": [item.symbol for item in chosen_series],
            "symbols_excluded": excluded_symbols,
            "common_days": len(aligned_dates),
            "symbol_provenance": symbol_provenance,
        },
    }
