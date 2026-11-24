"""Orchestration: collect -> prices -> classify -> backtest -> summary -> site."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, prices, storage
from .backtest import run_backtest
from .classify_runner import run_classification
from .filters import to_disclosure
from .site.build import build_site
from .stats import summarize

log = logging.getLogger(__name__)
FMT = "%Y%m%d"


def _days(start: str, end: str) -> list[str]:
    d, last = datetime.strptime(start, FMT).date(), datetime.strptime(end, FMT).date()
    out = []
    while d <= last:
        out.append(d.strftime(FMT))
        d += timedelta(days=1)
    return out


def _shift(day: str, days: int) -> str:
    return (datetime.strptime(day, FMT).date() + timedelta(days=days)).strftime(FMT)


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def collect(root: Path, dart, start: str, end: str, move_state: bool) -> dict:
    totals = {"fetched": 0, "listed": 0, "candidates": 0, "new": 0}
    for day in _days(start, end):
        rows = [r for m in config.MARKETS for t in config.PBLNTF_TYPES for r in dart.list_disclosures(day, m, t)]
        items = [d for d in (to_disclosure(r) for r in rows) if d is not None]
        record = {
            "fetched": len(rows),
            "listed": len(items),
            "candidates": sum(1 for d in items if d.candidate_type and not d.is_correction),
            "new": storage.append_disclosures(items, root),
        }
        storage.append_ops_log(root, {"kind": "collect", "date": day, **record})
        totals = {k: totals[k] + record[k] for k in totals}
        log.info("collected %s: %s", day, record)
    if move_state:
        last = storage.read_state(root).get("last_collected_date")
        if last is None or end > last:
            storage.write_state(root, {**storage.read_state(root), "last_collected_date": end})
    return totals


def refresh_results(root: Path) -> int:
    """Re-run the backtest, rewrite summary.json, rebuild the site. Returns event count."""
    events = run_backtest(root)
    summary = summarize(storage.load_classifications(root), events, _now().isoformat())
    path = root / "results" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    build_site(root, config.SITE_DIR)
    return len(events)


def daily(root: Path, today: date, dart, krx, classifier) -> dict:
    end = (today - timedelta(days=1)).strftime(FMT)
    last = storage.read_state(root).get("last_collected_date")
    start = _shift(last, 1) if last else end
    collected = collect(root, dart, start, end, move_state=True) if start <= end else {}
    downloaded = prices.download_range(krx, _shift(min(start, end), -config.PRICE_LOOKBACK_DAYS), end, root)
    classified = run_classification(root, dart, classifier, config.DAILY_REQUEST_CAP, _now)
    storage.append_ops_log(
        root, {"kind": "run", "at": _now().isoformat(), "start": start, "end": end, **classified}
    )
    n_events = refresh_results(root)
    return {"start": start, "end": end, "collect": collected, "prices": downloaded,
            "classify": classified, "events": n_events}


def backfill(root: Path, start: str, end: str, dart, krx) -> dict:
    collected = collect(root, dart, start, end, move_state=False)
    downloaded = prices.download_range(krx, _shift(start, -config.PRICE_LOOKBACK_DAYS), end, root)
    return {"start": start, "end": end, "collect": collected, "prices": downloaded}
