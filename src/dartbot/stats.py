"""Validation statistics, kept separate per (origin, classifier_version)."""
from __future__ import annotations

import math

from scipy import stats as scipy_stats

from . import config
from .backtest import actual_label, judge
from .models import Classification, EventResult

CONFIDENCE_BUCKETS = (("0.0-0.5", 0.0, 0.5), ("0.5-0.7", 0.5, 0.7), ("0.7-0.9", 0.7, 0.9), ("0.9-1.0", 0.9, 1.0001))


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _p_value(values: list[float]) -> float | None:
    if len(values) < 2 or max(values) - min(values) < 1e-12:  # no variance -> t-test undefined
        return None
    p = float(scipy_stats.ttest_1samp(values, 0.0).pvalue)
    return None if math.isnan(p) else p


def _mean_block(values: list[float]) -> dict:
    return {
        "mean": sum(values) / len(values) if values else None,
        "n": len(values),
        "p_value": _p_value(values),
        "insufficient": len(values) < config.MIN_SAMPLE,
    }


def _group_summary(pairs: list[tuple[Classification, EventResult | None]]) -> dict:
    ok = [(c, e) for c, e in pairs if e is not None and e.status == "ok"]
    primary, thr = config.PRIMARY_WINDOW, config.PRIMARY_THRESHOLD

    by_sentiment = {
        s: {
            str(w): _mean_block([e.car[w] for c, e in ok if c.sentiment == s and e.car.get(w) is not None])
            for w in config.CAR_WINDOWS
        }
        for s in config.SENTIMENTS
    }

    by_type = {}
    for t in config.TYPES:
        rows = [(c, e) for c, e in ok if c.type == t]
        if rows:
            cars = [e.car[primary] for _, e in rows]
            by_type[t] = {
                "n": len(rows),
                "mean_car1": sum(cars) / len(cars),
                "hit_rate": _rate([judge(c.sentiment, e.car[primary], thr) for c, e in rows]),
                "insufficient": len(rows) < config.MIN_SAMPLE,
            }

    confusion = {p: {a: 0 for a in config.SENTIMENTS} for p in config.SENTIMENTS}
    for c, e in ok:
        confusion[c.sentiment][actual_label(e.car[primary], thr)] += 1

    directional = [
        (e.car[primary] > 0) if c.sentiment == "긍정" else (e.car[primary] < 0)
        for c, e in ok
        if c.sentiment != "중립"
    ]

    return {
        "n_classified": len(pairs),
        "n_ok": len(ok),
        "n_pending": sum(1 for _, e in pairs if e is not None and e.status == "pending"),
        "n_no_price": sum(1 for _, e in pairs if e is not None and e.status == "no_price"),
        "by_sentiment": by_sentiment,
        "by_type": by_type,
        "confusion": confusion,
        "directional_hit_rate": _rate(directional),
        "hit_rate_by_threshold": {
            str(t): _rate([judge(c.sentiment, e.car[primary], t) for c, e in ok]) for t in config.THRESHOLDS
        },
        "hit_rate_by_confidence": {
            label: _rate([judge(c.sentiment, e.car[primary], thr) for c, e in ok if lo <= c.confidence < hi])
            for label, lo, hi in CONFIDENCE_BUCKETS
        },
    }


def summarize(classifications: list[Classification], events: list[EventResult], now: str) -> dict:
    by_id = {e.rcept_no: e for e in events}
    groups: dict[tuple[str, str], list[tuple[Classification, EventResult | None]]] = {}
    for c in classifications:
        if c.type == "기타":  # not an event type; judged per classification, not per latest
            continue
        groups.setdefault((c.origin, c.classifier_version), []).append((c, by_id.get(c.rcept_no)))
    return {
        "generated_at": now,
        "groups": [
            {"origin": origin, "classifier_version": version, **_group_summary(pairs)}
            for (origin, version), pairs in sorted(groups.items())
        ],
    }
