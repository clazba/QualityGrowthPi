"""Polygon market data adapter scaffold with explicit fidelity caveats."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

from src.models import FundamentalSnapshot
from src.provider_adapters.base import MarketDataProvider, ProviderError


class PolygonAdapter(MarketDataProvider):
    """Polygon adapter for approximate local workflows."""

    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def provider_name(self) -> str:
        return "polygon"

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("POLYGON_API_KEY is not configured")
        payload = dict(params or {})
        payload["apiKey"] = self.api_key
        response = self.session.get(f"{self.base_url}{path}", params=payload, timeout=10)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError(f"Polygon request failed: {exc}") from exc
        return response.json()

    def fetch_fundamentals(self, as_of: datetime | None = None) -> list[FundamentalSnapshot]:
        raise ProviderError(
            "Polygon field mappings for Morningstar-equivalent quality metrics are intentionally not assumed "
            "in this scaffold. Implement and validate the exact field mapping before using external_equivalent "
            "mode for production comparisons."
        )

    def fetch_daily_bars(self, symbol: str, lookback_days: int) -> dict[str, list[float]]:
        end = datetime.now(UTC).date()
        start = end.fromordinal(end.toordinal() - max(lookback_days * 2, lookback_days))
        payload = self._request(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            params={"adjusted": "true", "sort": "asc", "limit": 5000},
        )
        results = payload.get("results", [])
        closes = [float(item["c"]) for item in results][-lookback_days:]
        volumes = [float(item["v"]) for item in results][-lookback_days:]
        if not closes or not volumes:
            raise ProviderError(f"No Polygon daily bars returned for {symbol}")
        return {"closes": closes, "volumes": volumes}
