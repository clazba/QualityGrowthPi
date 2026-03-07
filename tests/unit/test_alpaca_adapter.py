"""Unit tests for Alpaca execution and daily-bar adapters."""

from datetime import UTC, datetime

from src.provider_adapters.alpaca_adapter import AlpacaExecutionAdapter, AlpacaMarketDataAdapter


def test_alpaca_execution_adapter_validates_paper_credentials() -> None:
    adapter = AlpacaExecutionAdapter(
        api_key="key",
        api_secret="secret",
        environment="paper",
        trading_base_url="https://paper-api.alpaca.markets",
    )
    adapter.validate(paper=True)


def test_alpaca_market_data_adapter_normalizes_bar_payload() -> None:
    payload = {
        "bars": [
            {"t": "2026-03-05T00:00:00Z", "c": 100.5, "v": 250000},
            {"t": "2026-03-06T00:00:00Z", "c": 101.0, "v": 260000},
        ]
    }
    adapter = AlpacaMarketDataAdapter(api_key="key", api_secret="secret")
    normalized = adapter._normalize_bar_payload(payload)
    assert normalized[0]["close"] == 100.5
    assert normalized[1]["volume"] == 260000.0


def test_alpaca_market_data_adapter_supports_symbol_keyed_bars_payload() -> None:
    payload = {
        "bars": {
            "SPY": [
                {"t": "2026-03-05T00:00:00Z", "c": 600.5, "v": 1500000},
                {"t": "2026-03-06T00:00:00Z", "c": 601.0, "v": 1510000},
            ]
        }
    }
    adapter = AlpacaMarketDataAdapter(api_key="key", api_secret="secret")
    normalized = adapter._normalize_bar_payload(payload)
    assert len(normalized) == 2
    assert normalized[0]["close"] == 600.5


def test_alpaca_market_data_adapter_requests_explicit_date_window() -> None:
    class CapturingAdapter(AlpacaMarketDataAdapter):
        def __init__(self) -> None:
            super().__init__(api_key="key", api_secret="secret")
            self.captured_path = ""
            self.captured_params = {}

        def _request(self, path: str, params: dict[str, object]) -> dict[str, object]:
            self.captured_path = path
            self.captured_params = params
            return {
                "bars": [
                    {"t": "2026-03-03T00:00:00Z", "c": 100.0, "v": 1000},
                    {"t": "2026-03-04T00:00:00Z", "c": 101.0, "v": 1100},
                    {"t": "2026-03-05T00:00:00Z", "c": 102.0, "v": 1200},
                    {"t": "2026-03-06T00:00:00Z", "c": 103.0, "v": 1300},
                    {"t": "2026-03-07T00:00:00Z", "c": 104.0, "v": 1400},
                ]
            }

    adapter = CapturingAdapter()
    bars = adapter.fetch_daily_bars("AAPL", 5)
    assert adapter.captured_path.endswith("/AAPL/bars")
    assert adapter.captured_params["timeframe"] == "1Day"
    assert adapter.captured_params["feed"] == "iex"
    assert "start" in adapter.captured_params
    assert "end" in adapter.captured_params
    start_at = datetime.fromisoformat(str(adapter.captured_params["start"]).replace("Z", "+00:00"))
    end_at = datetime.fromisoformat(str(adapter.captured_params["end"]).replace("Z", "+00:00"))
    assert start_at.tzinfo == UTC
    assert end_at.tzinfo == UTC
    assert start_at < end_at
    assert bars["closes"][-1] == 104.0
