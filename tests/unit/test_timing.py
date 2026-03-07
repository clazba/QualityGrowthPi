"""Unit tests for timing overlay calculations."""

from src.settings import load_settings
from src.timing import build_timing_features


def test_timing_features_scores_all_three_signals() -> None:
    settings = load_settings()
    closes = [
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        111,
        112,
        113,
        114,
        114.2,
        114.4,
        114.6,
        114.8,
        115.0,
        115.2,
        115.4,
        115.6,
        115.8,
        116.0,
        116.2,
        116.4,
        116.6,
        116.8,
        117.0
    ]
    volumes = [100_000] * 29 + [180_000]
    features = build_timing_features("AAA", closes, volumes, settings.strategy)
    assert features.relative_volume > settings.strategy.timing.relative_volume_threshold
    assert features.volatility_contraction is True
    assert features.trend_up is True
    assert features.timing_score == 1.0
