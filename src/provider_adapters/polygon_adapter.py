"""Massive (formerly Polygon.io) market data adapter scaffold."""

from __future__ import annotations

import os
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlunparse

import requests

from src.models import FundamentalSnapshot
from src.provider_adapters.base import MarketDataProvider, ProviderError


class MassiveAdapter(MarketDataProvider):
    """Massive adapter for approximate local workflows."""

    DEFAULT_BASE_URL = "https://api.massive.com"
    DEFAULT_AGGREGATES_PATH_TEMPLATE = "/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}"
    DEFAULT_RATIOS_PATH_TEMPLATE = "/stocks/financials/v1/ratios"
    DEFAULT_INCOME_STATEMENTS_PATH_TEMPLATE = "/stocks/financials/v1/income-statements"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        aggregates_path_template: str | None = None,
        ratios_path_template: str | None = None,
        income_statements_path_template: str | None = None,
        fundamentals_cache_path: Path | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""
        self.base_url = (
            base_url
            or os.getenv("MASSIVE_BASE_URL")
            or os.getenv("POLYGON_BASE_URL")
            or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.aggregates_path_template = (
            aggregates_path_template
            or os.getenv("MASSIVE_AGGREGATES_PATH_TEMPLATE")
            or self.DEFAULT_AGGREGATES_PATH_TEMPLATE
        )
        self.ratios_path_template = (
            ratios_path_template
            or os.getenv("MASSIVE_RATIOS_PATH_TEMPLATE")
            or self.DEFAULT_RATIOS_PATH_TEMPLATE
        )
        self.income_statements_path_template = (
            income_statements_path_template
            or os.getenv("MASSIVE_INCOME_STATEMENTS_PATH_TEMPLATE")
            or self.DEFAULT_INCOME_STATEMENTS_PATH_TEMPLATE
        )
        self.fundamentals_cache_path = fundamentals_cache_path or Path(
            os.getenv(
                "MASSIVE_FUNDAMENTALS_CACHE_PATH",
                str(Path.cwd() / "data" / "market_cache" / "massive" / "fundamentals_snapshot.jsonl"),
            )
        )
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "massive"

    def _prepare_url_and_params(
        self,
        path_or_url: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return a request URL and query params with auth merged safely."""

        url = path_or_url if path_or_url.startswith("http://") or path_or_url.startswith("https://") else f"{self.base_url}{path_or_url}"
        payload = dict(params or {})
        parsed = urlparse(url)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "apiKey" not in query_params and "apiKey" not in payload:
            payload["apiKey"] = self.api_key
        if parsed.query:
            url = urlunparse(parsed._replace(query=""))
            payload = {**query_params, **payload}
        return url, payload

    def _request(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("MASSIVE_API_KEY is not configured (POLYGON_API_KEY is also accepted for compatibility)")
        url, payload = self._prepare_url_and_params(path_or_url, params=params)
        response = self.session.get(
            url,
            params=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Massive request failed: {exc}") from exc
        return response.json()

    def _build_aggregates_path(
        self,
        symbol: str,
        start: str,
        end: str,
        multiplier: int = 1,
        timespan: str = "day",
    ) -> str:
        """Build the configured aggregates endpoint path."""

        return self.aggregates_path_template.format_map(
            {
                "ticker": symbol,
                "stocksTicker": symbol,
                "multiplier": multiplier,
                "timespan": timespan,
                "start": start,
                "from": start,
                "end": end,
                "to": end,
            }
        )

    @staticmethod
    def _extract_bar_value(bar: dict[str, Any], *keys: str) -> Any:
        """Return the first present key from a bar payload."""

        for key in keys:
            if key in bar and bar[key] is not None:
                return bar[key]
        return None

    def _parse_aggregate_payload(self, payload: dict[str, Any]) -> list[dict[str, float]]:
        """Normalize Massive aggregate results while tolerating conservative schema drift."""

        status = str(payload.get("status", "OK")).upper()
        if status not in {"OK", "DELAYED", "SUCCESS"} and payload.get("results") is None:
            raise ProviderError(f"Massive aggregates request returned status={payload.get('status')!r}")

        raw_results = payload.get("results")
        if raw_results is None:
            return []
        if not isinstance(raw_results, list):
            raise ProviderError("Massive aggregates payload returned a non-list results field")

        parsed_results: list[dict[str, float]] = []
        for bar in raw_results:
            close_value = self._extract_bar_value(bar, "c", "close")
            volume_value = self._extract_bar_value(bar, "v", "volume")
            timestamp_value = self._extract_bar_value(bar, "t", "timestamp")
            if close_value is None or volume_value is None:
                continue
            parsed_results.append(
                {
                    "close": float(close_value),
                    "volume": float(volume_value),
                    "timestamp": float(timestamp_value) if timestamp_value is not None else 0.0,
                }
            )
        return parsed_results

    @staticmethod
    def _extract_nested_value(record: Any, *path: Any) -> Any:
        """Return a nested dictionary or list value if present."""

        current = record
        for step in path:
            if isinstance(step, int):
                if not isinstance(current, list) or step >= len(current):
                    return None
                current = current[step]
            else:
                if not isinstance(current, dict):
                    return None
                current = current.get(step)
            if current is None:
                return None
        return current

    @classmethod
    def _first_present(cls, record: dict[str, Any], *paths: tuple[Any, ...]) -> Any:
        """Return the first non-null value found across candidate paths."""

        for path in paths:
            value = cls._extract_nested_value(record, *path)
            if value is not None:
                return value
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        """Return a float or None when the input is empty or malformed."""

        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _paginate_results(self, path_or_url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Collect a paginated Massive `results` list via `next_url` links."""

        next_target: str | None = path_or_url
        request_params = dict(params or {}) if params else None
        seen_urls: set[str] = set()
        results: list[dict[str, Any]] = []

        while next_target:
            if next_target in seen_urls:
                raise ProviderError("Massive pagination returned a repeated next_url")
            seen_urls.add(next_target)
            payload = self._request(next_target, params=request_params)
            status = str(payload.get("status", "OK")).upper()
            if status not in {"OK", "DELAYED", "SUCCESS"} and payload.get("results") is None:
                raise ProviderError(f"Massive paginated request returned status={payload.get('status')!r}")

            batch = payload.get("results") or []
            if not isinstance(batch, list):
                raise ProviderError("Massive paginated payload returned a non-list results field")
            results.extend(batch)
            next_target = payload.get("next_url")
            request_params = None

        return results

    def list_financial_ratios(self, ticker: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """Return normalized ratio snapshots from Massive's v1 financial ratios endpoint."""

        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        raw_results = self._paginate_results(self.ratios_path_template, params=params)
        return [result for result in (self._normalize_ratio_record(record) for record in raw_results) if result]

    def list_income_statements(
        self,
        tickers: str | None = None,
        timeframe: str = "quarterly",
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return normalized income statement records from Massive's v1 financials endpoints."""

        params: dict[str, Any] = {"limit": limit, "timeframe": timeframe}
        if tickers:
            params["tickers"] = tickers
        raw_results = self._paginate_results(self.income_statements_path_template, params=params)
        results = [result for result in (self._normalize_income_statement_record(record) for record in raw_results) if result]
        return sorted(
            results,
            key=lambda item: (item["ticker"], item.get("filing_date") or "", item.get("period_end") or ""),
            reverse=True,
        )

    def _normalize_ratio_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a Massive financial ratios record."""

        ticker = self._first_present(record, ("ticker",), ("tickers", 0), ("symbols", 0))
        if ticker is None:
            return None
        return {
            "ticker": str(ticker),
            "cik": self._first_present(record, ("cik",)),
            "date": self._first_present(record, ("date",), ("as_of_date",)),
            "price": self._coerce_float(self._first_present(record, ("price",), ("close",))),
            "average_volume": self._coerce_float(self._first_present(record, ("average_volume",), ("avg_volume",))),
            "market_cap": self._coerce_float(self._first_present(record, ("market_cap",), ("marketCap",))),
            "earnings_per_share": self._coerce_float(
                self._first_present(record, ("earnings_per_share",), ("eps",))
            ),
            "price_to_earnings": self._coerce_float(
                self._first_present(record, ("price_to_earnings",), ("pe_ratio",))
            ),
            "return_on_equity": self._coerce_float(
                self._first_present(record, ("return_on_equity",), ("roe",))
            ),
            "debt_to_equity": self._coerce_float(
                self._first_present(record, ("debt_to_equity",), ("debtEquity",))
            ),
            "enterprise_value": self._coerce_float(
                self._first_present(record, ("enterprise_value",), ("enterpriseValue",))
            ),
            "free_cash_flow": self._coerce_float(
                self._first_present(record, ("free_cash_flow",), ("fcf",))
            ),
            "raw": record,
        }

    def _normalize_income_statement_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a Massive income statement record."""

        ticker = self._first_present(record, ("ticker",), ("tickers", 0), ("symbols", 0))
        if ticker is None:
            return None
        return {
            "ticker": str(ticker),
            "cik": self._first_present(record, ("cik",)),
            "period_end": self._first_present(record, ("period_end",), ("periodEnd",)),
            "filing_date": self._first_present(record, ("filing_date",), ("filingDate",)),
            "fiscal_quarter": self._first_present(record, ("fiscal_quarter",), ("fiscalQuarter",)),
            "fiscal_year": self._first_present(record, ("fiscal_year",), ("fiscalYear",)),
            "timeframe": self._first_present(record, ("timeframe",)),
            "revenue": self._coerce_float(self._first_present(record, ("revenue",), ("revenues",))),
            "gross_profit": self._coerce_float(self._first_present(record, ("gross_profit",),)),
            "cost_of_revenue": self._coerce_float(self._first_present(record, ("cost_of_revenue",),)),
            "operating_income": self._coerce_float(self._first_present(record, ("operating_income",),)),
            "net_income": self._coerce_float(
                self._first_present(
                    record,
                    ("net_income_loss_attributable_common_shareholders",),
                    ("consolidated_net_income_loss",),
                    ("net_income",),
                )
            ),
            "ebitda": self._coerce_float(self._first_present(record, ("ebitda",),)),
            "raw": record,
        }

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        if self.fundamentals_cache_path.exists():
            snapshots: list[FundamentalSnapshot] = []
            with self.fundamentals_cache_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    snapshot = FundamentalSnapshot(**json.loads(line))
                    if as_of and snapshot.as_of and snapshot.as_of > as_of:
                        continue
                    snapshots.append(snapshot)
            return snapshots
        raise ProviderError(
            f"Massive fundamentals cache not found: {self.fundamentals_cache_path}. "
            "Populate a normalized snapshot cache using list_financial_ratios() and list_income_statements() "
            "against the current /stocks/financials/v1 endpoints, then validate the remaining strategy-critical "
            "mappings (especially PEG, gross-margin methodology, and point-in-time growth calculations) before "
            "enabling external_equivalent mode for production comparisons."
        )

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        end = datetime.now(UTC).date()
        # Use a wider calendar buffer than the raw trading lookback to absorb weekends and holidays.
        start = end.fromordinal(end.toordinal() - max(lookback_days * 3, lookback_days + 30))
        next_target: str | None = self._build_aggregates_path(symbol, start.isoformat(), end.isoformat())
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
            payload = self._request(next_target, params=request_params)
            parsed_results.extend(self._parse_aggregate_payload(payload))
            next_target = payload.get("next_url")
            request_params = None

        closes = [item["close"] for item in parsed_results][-lookback_days:]
        volumes = [item["volume"] for item in parsed_results][-lookback_days:]
        if not closes or not volumes:
            raise ProviderError(f"No Massive daily bars returned for {symbol}")
        if len(closes) < lookback_days or len(volumes) < lookback_days:
            raise ProviderError(
                f"Insufficient Massive daily bars returned for {symbol}: "
                f"required={lookback_days} received={len(closes)}"
            )
        return {"closes": closes, "volumes": volumes}


# Backward-compatible alias while the repository transitions from Polygon naming to Massive naming.
PolygonAdapter = MassiveAdapter
