from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from src.stat_arb.data_export import export_aligned_price_history, load_symbol_price_series


def _write_symbol_zip(root: Path, symbol: str, rows: list[str]) -> None:
    daily_dir = root / "equity" / "usa" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    archive_path = daily_dir / f"{symbol.lower()}.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(f"{symbol.lower()}.csv", "\n".join(rows) + "\n")


def test_load_symbol_price_series_reads_lean_zip_payload(tmp_path: Path) -> None:
    _write_symbol_zip(
        tmp_path,
        "AAPL",
        [
            "20240102,100,101,99,100.5,1000000",
            "20240103,100,102,99,101.5,1100000",
            "20240104,101,103,100,102.5,1200000",
            "20240105,102,104,101,103.5,1200000",
            "20240108,103,105,102,104.5,1200000",
            "20240109,104,106,103,105.5,1200000",
            "20240110,105,107,104,106.5,1200000",
            "20240111,106,108,105,107.5,1200000",
            "20240112,107,109,106,108.5,1200000",
            "20240115,108,110,107,109.5,1200000",
        ],
    )

    series = load_symbol_price_series(tmp_path, "AAPL")

    assert series.symbol == "AAPL"
    assert series.closes_by_date["2024-01-02"] == 100.5
    assert series.closes_by_date["2024-01-15"] == 109.5


def test_export_aligned_price_history_intersects_calendar(tmp_path: Path) -> None:
    _write_symbol_zip(
        tmp_path,
        "AAPL",
        [
            "20240102,100,101,99,100.5,1000000",
            "20240103,100,102,99,101.5,1100000",
            "20240104,101,103,100,102.5,1200000",
            "20240105,102,104,101,103.5,1200000",
            "20240108,103,105,102,104.5,1200000",
            "20240109,104,106,103,105.5,1200000",
            "20240110,105,107,104,106.5,1200000",
            "20240111,106,108,105,107.5,1200000",
            "20240112,107,109,106,108.5,1200000",
            "20240115,108,110,107,109.5,1200000",
        ],
    )
    _write_symbol_zip(
        tmp_path,
        "MSFT",
        [
            "20240103,200,201,199,200.5,1000000",
            "20240104,200,202,199,201.5,1100000",
            "20240105,201,203,200,202.5,1200000",
            "20240108,202,204,201,203.5,1200000",
            "20240109,203,205,202,204.5,1200000",
            "20240110,204,206,203,205.5,1200000",
            "20240111,205,207,204,206.5,1200000",
            "20240112,206,208,205,207.5,1200000",
            "20240115,207,209,206,208.5,1200000",
            "20240116,208,210,207,209.5,1200000",
        ],
    )

    payload = export_aligned_price_history(tmp_path, ["AAPL", "MSFT"], minimum_common_days=5)

    assert payload["calendar"][0] == "2024-01-03"
    assert payload["calendar"][-1] == "2024-01-15"
    assert len(payload["calendar"]) == 9
    assert payload["price_history"]["AAPL"][0] == 101.5
    assert payload["price_history"]["MSFT"][0] == 200.5
