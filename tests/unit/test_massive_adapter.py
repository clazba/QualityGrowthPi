"""Unit tests for the Massive aggregates adapter."""

from src.provider_adapters.polygon_adapter import MassiveAdapter


def test_parse_aggregate_payload_supports_official_short_field_names() -> None:
    adapter = MassiveAdapter(api_key="test-key")
    payload = {
        "status": "OK",
        "results": [
            {"c": 100.5, "v": 250000, "t": 1730000000000},
            {"c": 101.0, "v": 260000, "t": 1730086400000},
        ],
    }
    parsed = adapter._parse_aggregate_payload(payload)
    assert parsed == [
        {"close": 100.5, "volume": 250000.0, "timestamp": 1730000000000.0},
        {"close": 101.0, "volume": 260000.0, "timestamp": 1730086400000.0},
    ]


def test_parse_aggregate_payload_tolerates_expanded_field_names() -> None:
    adapter = MassiveAdapter(api_key="test-key")
    payload = {
        "status": "SUCCESS",
        "results": [
            {"close": 100.5, "volume": 250000, "timestamp": 1730000000000},
            {"close": 101.0, "volume": 260000, "timestamp": 1730086400000},
        ],
    }
    parsed = adapter._parse_aggregate_payload(payload)
    assert parsed[0]["close"] == 100.5
    assert parsed[1]["volume"] == 260000.0


def test_fetch_daily_bars_follows_next_url_and_returns_last_lookback_days() -> None:
    adapter = MassiveAdapter(api_key="test-key")
    calls: list[tuple[str, dict | None]] = []
    payloads = [
        {
            "status": "OK",
            "results": [
                {"c": 100.0, "v": 1000, "t": 1},
                {"c": 101.0, "v": 1100, "t": 2},
            ],
            "next_url": "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-03-01?cursor=abc",
        },
        {
            "status": "OK",
            "results": [
                {"c": 102.0, "v": 1200, "t": 3},
                {"c": 103.0, "v": 1300, "t": 4},
            ],
        },
    ]

    def fake_request(path_or_url: str, params: dict | None = None) -> dict:
        calls.append((path_or_url, params))
        return payloads[len(calls) - 1]

    adapter._request = fake_request  # type: ignore[method-assign]
    result = adapter.fetch_daily_bars("AAPL", lookback_days=3)
    assert result == {"closes": [101.0, 102.0, 103.0], "volumes": [1100.0, 1200.0, 1300.0]}
    assert calls[0][1] is not None
    assert calls[1][0].startswith("https://api.massive.com/")


def test_build_aggregates_path_is_overrideable_for_endpoint_migrations() -> None:
    adapter = MassiveAdapter(
        api_key="test-key",
        aggregates_path_template="/v3/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}",
    )
    path = adapter._build_aggregates_path("AAPL", "2024-01-01", "2024-03-01")
    assert path == "/v3/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-03-01"
