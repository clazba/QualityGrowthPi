"""LEAN workspace unit test coverage for shared scoring imports."""

from src.models import FundamentalSnapshot
from src.scoring import rank_fundamental_candidates
from src.settings import load_settings


def test_shared_scoring_imports() -> None:
    settings = load_settings()
    ranked = rank_fundamental_candidates(
        [
            FundamentalSnapshot(
                symbol="AAA",
                market_cap=2_000_000_000,
                exchange_id="NYS",
                price=25,
                volume=100_000,
                roe=0.20,
                gross_margin=0.45,
                debt_to_equity=0.5,
                revenue_growth=0.20,
                net_income_growth=0.15,
                pe_ratio=20,
                peg_ratio=1.5,
            )
        ],
        settings.strategy,
    )
    assert ranked[0].symbol == "AAA"
