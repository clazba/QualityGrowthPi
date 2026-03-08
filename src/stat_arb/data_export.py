"""Export aligned stat-arb training price history from LEAN-style daily data."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile


COMMON_DAILY_PATHS = (
    Path("equity/usa/daily"),
    Path("data/equity/usa/daily"),
)


@dataclass(frozen=True)
class SymbolPriceSeries:
    """Aligned daily closes discovered for one symbol."""

    symbol: str
    source_path: Path
    closes_by_date: dict[str, float]


def _candidate_paths(root: Path, symbol: str) -> list[Path]:
    lowered = symbol.lower()
    paths: list[Path] = []
    for prefix in COMMON_DAILY_PATHS:
        paths.extend(
            [
                root / prefix / f"{lowered}.zip",
                root / prefix / f"{lowered}.csv",
                root / prefix / f"{symbol}.zip",
                root / prefix / f"{symbol}.csv",
            ]
        )
    paths.extend(
        [
            root / f"{lowered}.zip",
            root / f"{lowered}.csv",
            root / f"{symbol}.zip",
            root / f"{symbol}.csv",
        ]
    )
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return ordered


def find_symbol_data_file(root: str | Path, symbol: str) -> Path:
    """Find the most likely LEAN daily data file for a symbol."""

    root_path = Path(root).expanduser().resolve()
    for candidate in _candidate_paths(root_path, symbol):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find LEAN daily data for {symbol} under {root_path}. "
        "Expected files like equity/usa/daily/<symbol>.zip"
    )


def _read_csv_rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError(f"{path} does not contain a CSV payload")
            member_name = sorted(csv_members)[0]
            payload = archive.read(member_name).decode("utf-8")
        handle = io.StringIO(payload)
    else:
        handle = path.open("r", encoding="utf-8")

    try:
        reader = csv.reader(handle)
        return [row for row in reader if row]
    finally:
        handle.close()


def _normalize_date(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    raise ValueError(f"Unable to parse trading date from value '{value}'")


def load_symbol_price_series(root: str | Path, symbol: str) -> SymbolPriceSeries:
    """Load daily close history for one symbol from LEAN-style CSV/ZIP data."""

    path = find_symbol_data_file(root, symbol)
    rows = _read_csv_rows(path)
    closes_by_date: dict[str, float] = {}
    for row in rows:
        if len(row) < 5:
            continue
        raw_date = row[0].strip()
        if not raw_date:
            continue
        try:
            trading_date = _normalize_date(raw_date)
            close = float(row[4])
        except ValueError:
            continue
        closes_by_date[trading_date] = close
    if len(closes_by_date) < 10:
        raise ValueError(f"{path} does not contain enough daily bars for {symbol}")
    return SymbolPriceSeries(
        symbol=symbol.upper(),
        source_path=path,
        closes_by_date=closes_by_date,
    )


def export_aligned_price_history(
    root: str | Path,
    symbols: list[str],
    *,
    minimum_common_days: int = 60,
) -> dict[str, object]:
    """Export aligned calendar + closes across the requested symbols."""

    if len(symbols) < 2:
        raise ValueError("At least two symbols are required to export stat-arb training history")
    series = [load_symbol_price_series(root, symbol) for symbol in symbols]
    common_dates = set(series[0].closes_by_date)
    for item in series[1:]:
        common_dates &= set(item.closes_by_date)
    aligned_dates = sorted(common_dates)
    if len(aligned_dates) < minimum_common_days:
        raise ValueError(
            f"Only {len(aligned_dates)} common daily bars were found across the requested universe; "
            f"at least {minimum_common_days} are required"
        )

    return {
        "calendar": aligned_dates,
        "price_history": {
            item.symbol: [item.closes_by_date[date] for date in aligned_dates]
            for item in series
        },
        "metadata": {
            "symbols": [item.symbol for item in series],
            "source_paths": {item.symbol: str(item.source_path) for item in series},
            "common_days": len(aligned_dates),
        },
    }


def write_price_history_json(payload: dict[str, object], output_path: str | Path) -> Path:
    """Persist aligned price history to the trainer input format."""

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
