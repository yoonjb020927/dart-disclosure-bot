"""Daily price cache (all stocks + KOSPI/KOSDAQ per trading day) and return lookups.

Returns come from KRX FLUC_RT (change vs the adjusted base price), not from
close-to-close, so ex-rights days (무상증자, splits) don't create fake jumps.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import pandas as pd

from . import config

log = logging.getLogger(__name__)

STOCK_KINDS = {"stk": "Y", "ksq": "K"}


class RowSource(Protocol):
    def fetch(self, kind: str, date: str) -> list[dict]: ...


def _num(value) -> float | None:
    text = str(value).replace(",", "").strip()
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _stock_path(root: Path, d: str) -> Path:
    return root / "prices" / "stocks" / d[:4] / f"{d}.csv.gz"


def _index_path(root: Path, d: str) -> Path:
    return root / "prices" / "index" / d[:4] / f"{d}.csv.gz"


def _stock_frame(kind_rows: dict[str, list[dict]], d: str) -> pd.DataFrame:
    f = config.KRX_STOCK_FIELDS
    records = []
    for kind, market in STOCK_KINDS.items():
        for r in kind_rows[kind]:
            fluc = _num(r.get(f["fluc"]))
            if _num(r.get(f["volume"])) == 0:  # halted: KRX lists it with FLUC_RT 0.00
                fluc = None
            records.append(
                {
                    "date": d,
                    "code": str(r[f["code"]]).strip(),
                    "name": r.get(f["name"], ""),
                    "market": market,
                    "close": _num(r.get(f["close"])),
                    "ret": None if fluc is None else fluc / 100,
                }
            )
    return pd.DataFrame(records, columns=["date", "code", "name", "market", "close", "ret"])


def _index_frame(kind_rows: dict[str, list[dict]], d: str) -> pd.DataFrame:
    f = config.KRX_INDEX_FIELDS
    records = []
    for kind, (source_name, stored_name) in config.KRX_INDEX_NAMES.items():
        for r in kind_rows[kind]:
            if str(r.get(f["name"], "")).strip() == source_name:
                fluc = _num(r.get(f["fluc"]))
                records.append(
                    {
                        "date": d,
                        "index": stored_name,
                        "close": _num(r.get(f["close"])),
                        "ret": None if fluc is None else fluc / 100,
                    }
                )
    return pd.DataFrame(records, columns=["date", "index", "close", "ret"])


def download_day(client: RowSource, d: str, root: Path) -> bool:
    """Save one trading day. False (and nothing written) on a holiday."""
    stock_path, index_path = _stock_path(root, d), _index_path(root, d)
    if stock_path.exists() and index_path.exists():
        return True
    kind_rows = {kind: client.fetch(kind, d) for kind in config.KRX_ENDPOINTS}
    if not any(kind_rows.values()):
        return False
    stocks, index = _stock_frame(kind_rows, d), _index_frame(kind_rows, d)
    if stocks.empty or len(index) < len(config.KRX_INDEX_NAMES):
        log.warning("KRX %s incomplete (stocks=%d, index=%d); not saved, will retry", d, len(stocks), len(index))
        return False
    for path, frame in ((stock_path, stocks), (index_path, index)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, compression="gzip")
    return True


def download_range(client: RowSource, start: str, end: str, root: Path) -> int:
    """Fetch every weekday in [start, end] not yet cached; return new trading days saved."""
    fmt = "%Y%m%d"
    current: date = datetime.strptime(start, fmt).date()
    last: date = datetime.strptime(end, fmt).date()
    saved = 0
    while current <= last:
        d = current.strftime(fmt)
        if current.weekday() < 5 and not (_stock_path(root, d).exists() and _index_path(root, d).exists()):
            saved += int(download_day(client, d, root))
        current += timedelta(days=1)
    _stock_day.cache_clear()
    _index_day.cache_clear()
    return saved


def trading_days(root: Path) -> list[str]:
    base = root / "prices" / "stocks"
    if not base.exists():
        return []
    return sorted(p.name.split(".")[0] for p in base.glob("*/*.csv.gz"))


@lru_cache(maxsize=512)
def _stock_day(root: str, d: str) -> dict[str, float | None]:
    path = _stock_path(Path(root), d)
    if not path.exists():
        return {}
    frame = pd.read_csv(path, dtype={"code": str})
    return {row.code: (None if pd.isna(row.ret) else float(row.ret)) for row in frame.itertuples()}


@lru_cache(maxsize=512)
def _index_day(root: str, d: str) -> dict[str, float | None]:
    path = _index_path(Path(root), d)
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    return {row.index: (None if pd.isna(row.ret) else float(row.ret)) for row in frame.itertuples(index=False)}


def stock_returns(root: Path, code: str, days: list[str]) -> list[float | None]:
    return [_stock_day(str(root), d).get(code) for d in days]


def market_returns(root: Path, market: str, days: list[str]) -> list[float | None]:
    name = config.MARKET_INDEX[market]
    return [_index_day(str(root), d).get(name) for d in days]
