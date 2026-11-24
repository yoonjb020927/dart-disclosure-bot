"""Event study: market-adjusted cumulative abnormal return (CAR) after each filing.

CAR[k] = sum over t0..t0+k of (stock return - market index return). The base is
the close before t0, so intraday and after-close filings are both captured.
"""
from __future__ import annotations

import bisect
import json
from pathlib import Path

from . import config, prices, storage
from .models import Classification, Disclosure, EventResult

EVENTS_FILE = Path("results") / "events.jsonl"
SOURCE = "krx"


def event_t0(rcept_dt: str, days: list[str]) -> str | None:
    i = bisect.bisect_left(days, rcept_dt)
    return days[i] if i < len(days) else None


def _window_car(d: Disclosure, root: Path, window: list[str]) -> float | None:
    stock = prices.stock_returns(root, d.stock_code, window)
    market = prices.market_returns(root, d.corp_cls, window)
    if any(r is None for r in stock) or any(r is None for r in market):
        return None
    return sum(s - m for s, m in zip(stock, market))


def compute_event(d: Disclosure, root: Path, days: list[str]) -> EventResult:
    t0 = event_t0(d.rcept_dt, days)
    if t0 is None:
        return EventResult(d.rcept_no, None, {k: None for k in config.CAR_WINDOWS}, "pending", SOURCE)
    start = days.index(t0)
    car: dict[int, float | None] = {}
    for k in config.CAR_WINDOWS:
        end = start + k
        car[k] = None if end >= len(days) else _window_car(d, root, days[start : end + 1])
    if start + config.PRIMARY_WINDOW >= len(days):
        status = "pending"
    elif car[config.PRIMARY_WINDOW] is None:
        status = "no_price"
    else:
        status = "ok"
    return EventResult(d.rcept_no, t0, car, status, SOURCE)


def judge(sentiment: str, car: float, threshold: float) -> bool:
    if sentiment == "긍정":
        return car > threshold
    if sentiment == "부정":
        return car < -threshold
    return abs(car) <= threshold


def actual_label(car: float, threshold: float) -> str:
    if car > threshold:
        return "긍정"
    if car < -threshold:
        return "부정"
    return "중립"


def latest_by_rcept(classifications: list[Classification]) -> dict[str, Classification]:
    latest: dict[str, Classification] = {}
    for c in classifications:
        if c.rcept_no not in latest or c.classified_at > latest[c.rcept_no].classified_at:
            latest[c.rcept_no] = c
    return latest


def run_backtest(root: Path) -> list[EventResult]:
    eventful = {c.rcept_no for c in storage.load_classifications(root) if c.type != "기타"}
    days = prices.trading_days(root)
    events = [
        compute_event(d, root, days)
        for d in storage.load_disclosures(root)
        if not d.is_correction and d.rcept_no in eventful
    ]
    path = root / EVENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in events), encoding="utf-8"
    )
    return events


def load_events(root: Path) -> list[EventResult]:
    path = root / EVENTS_FILE
    if not path.exists():
        return []
    return [EventResult.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]
