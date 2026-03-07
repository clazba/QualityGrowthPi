"""Unit tests for Alpha Vantage normalization paths."""

from src.provider_adapters.alpha_vantage_adapter import AlphaVantageAdapter, AlphaVantageNewsProvider


def test_alpha_vantage_daily_adjusted_payload_normalizes_adjusted_close() -> None:
    adapter = AlphaVantageAdapter(api_key="test-key")
    payload = {
        "Time Series (Daily)": {
            "2026-03-05": {
                "4. close": "101.50",
                "5. adjusted close": "100.50",
                "6. volume": "250000",
            },
            "2026-03-06": {
                "4. close": "102.00",
                "5. adjusted close": "101.00",
                "6. volume": "260000",
            },
        }
    }
    normalized = adapter._normalize_daily_adjusted_payload(payload)
    assert [row["close"] for row in normalized] == [100.5, 101.0]


def test_alpha_vantage_overview_normalizes_key_metrics() -> None:
    adapter = AlphaVantageAdapter(api_key="test-key")
    normalized = adapter._normalize_overview_record(
        {
            "Symbol": "AAPL",
            "Exchange": "NASDAQ",
            "MarketCapitalization": "3891743873600",
            "PERatio": "39.2",
            "PEGRatio": "2.1",
            "ReturnOnEquityTTM": "1.5081",
            "QuarterlyRevenueGrowthYOY": "0.08",
            "QuarterlyEarningsGrowthYOY": "0.11",
        }
    )
    assert normalized["symbol"] == "AAPL"
    assert normalized["pe_ratio"] == 39.2
    assert normalized["roe_ttm"] == 1.5081


def test_alpha_vantage_news_normalizes_feed_records() -> None:
    provider = AlphaVantageNewsProvider(api_key="test-key")
    events = provider._normalize_news_record(
        {
            "title": "Apple expands enterprise AI rollout",
            "summary": "Management reiterated infrastructure investment plans.",
            "url": "https://example.com/aapl-news",
            "source": "Alpha Vantage",
            "time_published": "20260307T090000",
            "ticker_sentiment": [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        },
        requested=["AAPL"],
    )
    assert len(events) == 1
    assert events[0].symbol == "AAPL"
    assert events[0].source == "Alpha Vantage"
