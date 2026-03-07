"""Alpaca execution and daily-bar adapters for paper-first workflows."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from src.provider_adapters.base import ExecutionProvider, MarketDataProvider, ProviderError


class AlpacaExecutionAdapter(ExecutionProvider):
    """Alpaca execution adapter with explicit paper-first validation."""

    PAPER_BASE_URL = "https://paper-api.alpaca.markets"
    LIVE_BASE_URL = "https://api.alpaca.markets"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        environment: str | None = None,
        trading_base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY") or ""
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET") or ""
        self.environment = (environment or os.getenv("ALPACA_ENVIRONMENT") or "paper").strip().lower()
        default_base_url = self.PAPER_BASE_URL if self.environment == "paper" else self.LIVE_BASE_URL
        self.trading_base_url = (trading_base_url or os.getenv("ALPACA_TRADING_BASE_URL") or default_base_url).rstrip("/")

    def provider_name(self) -> str:
        return "alpaca"

    def validate(self, paper: bool = True) -> None:
        if not self.api_key:
            raise ProviderError("ALPACA_API_KEY is not configured")
        if not self.api_secret:
            raise ProviderError("ALPACA_API_SECRET is not configured")
        if self.environment not in {"paper", "live"}:
            raise ProviderError("ALPACA_ENVIRONMENT must be 'paper' or 'live'")
        if paper and self.environment != "paper":
            raise ProviderError("Alpaca execution adapter is not configured for paper trading")

    def submit_target_weights(self, targets: dict[str, float], paper: bool = True) -> dict[str, Any]:
        self.validate(paper=paper)
        raise ProviderError(
            "Alpaca order submission is intentionally routed through LEAN deployment scripts in this scaffold. "
            "Use scripts/run_live_paper.sh for the first paper stage, then wire direct API submission only after "
            "paper validation, recovery procedures, and brokerage-specific contract tests are complete."
        )


class AlpacaMarketDataAdapter(MarketDataProvider):
    """Alpaca daily-bar adapter used in the local fallback stack."""

    DEFAULT_MARKET_DATA_BASE_URL = "https://data.alpaca.markets"
    DEFAULT_BARS_PATH_TEMPLATE = "/v2/stocks/{symbol}/bars"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        market_data_base_url: str | None = None,
        bars_path_template: str | None = None,
        feed: str | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY") or ""
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET") or ""
        self.market_data_base_url = (
            market_data_base_url or os.getenv("ALPACA_MARKET_DATA_BASE_URL") or self.DEFAULT_MARKET_DATA_BASE_URL
        ).rstrip("/")
        self.bars_path_template = (
            bars_path_template or os.getenv("ALPACA_BARS_PATH_TEMPLATE") or self.DEFAULT_BARS_PATH_TEMPLATE
        )
        self.feed = (feed or os.getenv("ALPACA_DATA_FEED") or "iex").strip().lower()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "alpaca"

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise ProviderError("ALPACA_API_KEY and ALPACA_API_SECRET are required for Alpaca market data")
        url = f"{self.market_data_base_url}{path}"
        response = self.session.get(
            url,
            params=params,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            },
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpaca request failed: {exc}") from exc
        return response.json()

    @staticmethod
    def _normalize_bar_payload(payload: dict[str, Any]) -> list[dict[str, float]]:
        has_bars_field = "bars" in payload
        bars = payload.get("bars")
        if bars is None:
            message = payload.get("message") or payload.get("error") or payload.get("detail")
            code = payload.get("code")
            keys = ",".join(sorted(str(key) for key in payload.keys()))
            symbol = payload.get("symbol")
            next_page_token = payload.get("next_page_token")
            detail_parts = [f"keys=[{keys}]"]
            detail_prefix = "Alpaca bars payload did not contain a 'bars' field"
            if has_bars_field:
                detail_prefix = "Alpaca bars payload contained 'bars' but its value was null"
            if code is not None:
                detail_parts.append(f"code={code}")
            if message:
                detail_parts.append(f"message={message}")
            if symbol:
                detail_parts.append(f"symbol={symbol}")
            if next_page_token is not None:
                detail_parts.append(f"next_page_token={next_page_token}")
            raise ProviderError(
                detail_prefix
                + (f" ({'; '.join(detail_parts)})" if detail_parts else "")
            )
        if isinstance(bars, dict):
            if len(bars) == 1:
                bars = next(iter(bars.values()))
            else:
                raise ProviderError(
                    "Alpaca bars payload returned a symbol-keyed mapping with multiple symbols; "
                    "the single-symbol adapter expected exactly one symbol."
                )
        if not isinstance(bars, list):
            raise ProviderError("Alpaca bars payload returned a non-list 'bars' field")

        normalized: list[dict[str, float]] = []
        for bar in bars:
            close_value = bar.get("c")
            volume_value = bar.get("v")
            timestamp_value = bar.get("t")
            if close_value is None or volume_value is None:
                continue
            normalized.append(
                {
                    "close": float(close_value),
                    "volume": float(volume_value),
                    "timestamp": float(datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).timestamp())
                    if timestamp_value
                    else 0.0,
                }
            )
        return normalized

    def fetch_fundamentals(self, as_of: datetime | None = None):  # type: ignore[override]
        raise ProviderError(
            "Alpaca does not provide the strategy's required fundamental universe fields. "
            "Use it for daily bars in the local fallback stack, not as the primary fundamentals source."
        )

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        path = self.bars_path_template.format(symbol=symbol)
        end_at = datetime.now(UTC)
        start_at = end_at - timedelta(days=max(lookback_days * 3, 45))
        params = {
            "timeframe": "1Day",
            "limit": max(lookback_days, 30),
            "adjustment": "all",
            "feed": self.feed,
            "sort": "asc",
            "start": start_at.isoformat().replace("+00:00", "Z"),
            "end": end_at.isoformat().replace("+00:00", "Z"),
        }
        payload = self._request(path, params=params)
        normalized = self._normalize_bar_payload(payload)
        closes = [bar["close"] for bar in normalized][-lookback_days:]
        volumes = [bar["volume"] for bar in normalized][-lookback_days:]
        if len(closes) < lookback_days or len(volumes) < lookback_days:
            raise ProviderError(
                f"Insufficient Alpaca daily bars returned for {symbol}: required={lookback_days} received={len(closes)}"
            )
        return {"closes": closes, "volumes": volumes}
