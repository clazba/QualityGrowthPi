"""Alpha Vantage market-data and news adapters for fallback workflows."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from src.models import FundamentalSnapshot, NewsEvent
from src.provider_adapters.base import MarketDataProvider, NewsProvider, ProviderError


class AlphaVantageAdapter(MarketDataProvider):
    """Alpha Vantage adapter for low-cost fallback daily bars and cached fundamentals."""

    DEFAULT_BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        fundamentals_cache_path: Path | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY") or ""
        self.base_url = base_url or os.getenv("ALPHA_VANTAGE_BASE_URL") or self.DEFAULT_BASE_URL
        self.fundamentals_cache_path = fundamentals_cache_path or Path(
            os.getenv(
                "ALPHA_VANTAGE_FUNDAMENTALS_CACHE_PATH",
                str(Path.cwd() / "data" / "market_cache" / "alpha_vantage" / "fundamentals_snapshot.jsonl"),
            )
        )
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "alpha_vantage"

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY is not configured")
        payload = {**params, "apikey": self.api_key}
        response = self.session.get(self.base_url, params=payload, timeout=self.timeout_seconds)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpha Vantage request failed: {exc}") from exc
        decoded = response.json()
        if "Note" in decoded:
            raise ProviderError(f"Alpha Vantage throttled: {decoded['Note']}")
        if "Information" in decoded:
            raise ProviderError(f"Alpha Vantage information response: {decoded['Information']}")
        if "Error Message" in decoded:
            raise ProviderError(f"Alpha Vantage request returned an error: {decoded['Error Message']}")
        return decoded

    @staticmethod
    def _normalize_daily_adjusted_payload(payload: dict[str, Any]) -> list[dict[str, float]]:
        series = payload.get("Time Series (Daily)")
        if series is None or not isinstance(series, dict):
            raise ProviderError("Alpha Vantage daily payload did not contain 'Time Series (Daily)'")

        normalized: list[dict[str, float]] = []
        for ts, bar in sorted(series.items()):
            adjusted_close = bar.get("5. adjusted close") or bar.get("4. close")
            volume = bar.get("6. volume") or bar.get("5. volume")
            if adjusted_close is None or volume is None:
                continue
            normalized.append(
                {
                    "timestamp": float(datetime.fromisoformat(ts).replace(tzinfo=UTC).timestamp()),
                    "close": float(adjusted_close),
                    "volume": float(volume),
                }
            )
        return normalized

    @staticmethod
    def _normalize_overview_record(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": record.get("Symbol"),
            "exchange": record.get("Exchange"),
            "market_cap": float(record["MarketCapitalization"]) if record.get("MarketCapitalization") else None,
            "pe_ratio": float(record["PERatio"]) if record.get("PERatio") else None,
            "peg_ratio": float(record["PEGRatio"]) if record.get("PEGRatio") else None,
            "roe_ttm": float(record["ReturnOnEquityTTM"]) if record.get("ReturnOnEquityTTM") else None,
            "profit_margin": float(record["ProfitMargin"]) if record.get("ProfitMargin") else None,
            "quarterly_revenue_growth_yoy": float(record["QuarterlyRevenueGrowthYOY"])
            if record.get("QuarterlyRevenueGrowthYOY")
            else None,
            "quarterly_earnings_growth_yoy": float(record["QuarterlyEarningsGrowthYOY"])
            if record.get("QuarterlyEarningsGrowthYOY")
            else None,
            "raw": record,
        }

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        if not self.fundamentals_cache_path.exists():
            raise ProviderError(
                f"Alpha Vantage fundamentals cache not found: {self.fundamentals_cache_path}. "
                "Populate a normalized snapshot cache before using Alpha Vantage in the local fallback stack."
            )
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

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        payload = self._request(
            {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": symbol,
                "outputsize": "full",
            }
        )
        normalized = self._normalize_daily_adjusted_payload(payload)
        closes = [bar["close"] for bar in normalized][-lookback_days:]
        volumes = [bar["volume"] for bar in normalized][-lookback_days:]
        if len(closes) < lookback_days or len(volumes) < lookback_days:
            raise ProviderError(
                f"Insufficient Alpha Vantage daily bars returned for {symbol}: required={lookback_days} received={len(closes)}"
            )
        return {"closes": closes, "volumes": volumes}


class AlphaVantageNewsProvider(NewsProvider):
    """Alpha Vantage NEWS_SENTIMENT adapter for LLM enrichment."""

    DEFAULT_BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY") or ""
        self.base_url = base_url or os.getenv("ALPHA_VANTAGE_BASE_URL") or self.DEFAULT_BASE_URL
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "alpha_vantage"

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY is not configured")
        response = self.session.get(
            self.base_url,
            params={**params, "apikey": self.api_key},
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpha Vantage news request failed: {exc}") from exc
        decoded = response.json()
        if "Note" in decoded:
            raise ProviderError(f"Alpha Vantage throttled: {decoded['Note']}")
        if "Information" in decoded:
            raise ProviderError(f"Alpha Vantage information response: {decoded['Information']}")
        if "Error Message" in decoded:
            raise ProviderError(f"Alpha Vantage news request returned an error: {decoded['Error Message']}")
        return decoded

    @staticmethod
    def _parse_time_published(raw_value: str) -> datetime:
        normalized = raw_value.strip()
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(normalized, fmt)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except ValueError:
                continue
        return datetime.fromisoformat(normalized).astimezone(UTC)

    @classmethod
    def _normalize_news_record(cls, record: dict[str, Any], requested: list[str]) -> list[NewsEvent]:
        tickers = [str(value).upper() for value in record.get("ticker_sentiment", []) if isinstance(value, dict) for value in [value.get("ticker")] if value]
        matched_tickers = [ticker for ticker in tickers if not requested or ticker in requested]
        if not matched_tickers:
            return []
        published_at = cls._parse_time_published(str(record.get("time_published", "")))
        events: list[NewsEvent] = []
        for ticker in matched_tickers:
            events.append(
                NewsEvent(
                    event_id=f"{record.get('url', 'alpha-vantage')}:{ticker}:{published_at.isoformat()}",
                    symbol=ticker,
                    headline=str(record.get("title", "")),
                    body=str(record.get("summary", "")),
                    source=str(record.get("source", "alpha_vantage")),
                    published_at=published_at,
                    url=str(record.get("url")) if record.get("url") else None,
                )
            )
        return events

    def fetch_news(self, symbols: list[str], since: datetime | None = None) -> list[NewsEvent]:
        requested = sorted({symbol.upper() for symbol in symbols if symbol})
        payload = self._request(
            {
                "function": "NEWS_SENTIMENT",
                "tickers": ",".join(requested),
                "limit": 50,
            }
        )
        raw_feed = payload.get("feed")
        if raw_feed is None:
            raise ProviderError("Alpha Vantage NEWS_SENTIMENT payload did not contain 'feed'")
        if not isinstance(raw_feed, list):
            raise ProviderError("Alpha Vantage NEWS_SENTIMENT payload returned a non-list 'feed'")
        events: list[NewsEvent] = []
        for record in raw_feed:
            events.extend(self._normalize_news_record(record, requested=requested))
        if since is not None:
            events = [event for event in events if event.published_at >= since]
        return sorted(events, key=lambda item: (item.symbol, item.published_at))
