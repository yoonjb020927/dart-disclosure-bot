import json
from datetime import date, timedelta

import pandas as pd
import pytest

from dartbot import backtest, storage
from dartbot.models import EventResult
from tests.test_models import make_classification, make_disclosure


def weekdays(start: date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2026, 10, 1), 25)  # 20261001 (Thu) ...


def write_prices(root, stock_rets: dict[str, list], market_rets: list, days=DAYS):
    """stock_rets: code -> list of returns aligned with days (None = no row)."""
    for i, d in enumerate(days):
        rows = [
            {"date": d, "code": code, "name": code, "market": "Y", "close": 1.0, "ret": rets[i]}
            for code, rets in stock_rets.items()
            if rets[i] is not None
        ]
        for sub, frame in (
            ("stocks", pd.DataFrame(rows, columns=["date", "code", "name", "market", "close", "ret"])),
            ("index", pd.DataFrame([{"date": d, "index": "KOSPI", "close": 1.0, "ret": market_rets[i]}])),
        ):
            path = root / "prices" / sub / d[:4] / f"{d}.csv.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False, compression="gzip")


def test_t0_weekend_rolls_to_next_trading_day():
    # 20261003 is Saturday -> next trading day Monday 20261005
    assert backtest.event_t0("20261003", DAYS) == "20261005"
    assert backtest.event_t0("20261002", DAYS) == "20261002"
    assert backtest.event_t0("20991231", DAYS) is None


def test_car_window_sums_excess_returns(tmp_path):
    stock = [0.0] * 25
    stock[3], stock[4] = 0.03, 0.01
    market = [0.0] * 25
    market[3] = 0.01
    write_prices(tmp_path, {"005930": stock}, market)
    d = make_disclosure(rcept_dt=DAYS[3], stock_code="005930", corp_cls="Y")
    e = backtest.compute_event(d, tmp_path, DAYS)
    assert e.status == "ok" and e.t0 == DAYS[3]
    assert e.car[1] == pytest.approx(0.03)
    assert e.car[5] == pytest.approx(0.03)
    assert e.car[20] == pytest.approx(0.03)


def test_pending_when_window_not_elapsed(tmp_path):
    write_prices(tmp_path, {"005930": [0.0] * 25}, [0.0] * 25)
    d = make_disclosure(rcept_dt=DAYS[-1], stock_code="005930")
    e = backtest.compute_event(d, tmp_path, DAYS)
    assert e.status == "pending" and e.car[1] is None


def test_pending_when_filed_after_last_trading_day(tmp_path):
    write_prices(tmp_path, {"005930": [0.0] * 25}, [0.0] * 25)
    e = backtest.compute_event(make_disclosure(rcept_dt="20991231"), tmp_path, DAYS)
    assert e.status == "pending" and e.t0 is None


def test_no_price_when_halted(tmp_path):
    stock = [0.0] * 25
    stock[4] = None  # trading halt on t0+1
    write_prices(tmp_path, {"005930": stock}, [0.0] * 25)
    e = backtest.compute_event(make_disclosure(rcept_dt=DAYS[3], stock_code="005930"), tmp_path, DAYS)
    assert e.status == "no_price"
    assert e.car[1] is None


def test_long_window_none_but_primary_ok(tmp_path):
    write_prices(tmp_path, {"005930": [0.0] * 25}, [0.0] * 25)
    e = backtest.compute_event(make_disclosure(rcept_dt=DAYS[10], stock_code="005930"), tmp_path, DAYS)
    assert e.status == "ok"
    assert e.car[1] is not None and e.car[20] is None


@pytest.mark.parametrize(
    "sentiment, car, threshold, expected",
    [
        ("긍정", 0.011, 0.01, True),
        ("긍정", 0.01, 0.01, False),
        ("중립", -0.01, 0.01, True),
        ("부정", -0.02, 0.01, True),
        ("부정", 0.0, 0.01, False),
    ],
)
def test_judge(sentiment, car, threshold, expected):
    assert backtest.judge(sentiment, car, threshold) is expected


def test_actual_label():
    assert backtest.actual_label(0.02, 0.01) == "긍정"
    assert backtest.actual_label(-0.02, 0.01) == "부정"
    assert backtest.actual_label(0.005, 0.01) == "중립"


def test_run_backtest_skips_corrections_other_and_unclassified(tmp_path):
    write_prices(tmp_path, {"005930": [0.01] * 25}, [0.0] * 25)
    keep = make_disclosure(rcept_no=DAYS[3] + "000001", rcept_dt=DAYS[3])
    correction = make_disclosure(rcept_no=DAYS[3] + "000002", rcept_dt=DAYS[3], is_correction=True)
    other = make_disclosure(rcept_no=DAYS[3] + "000003", rcept_dt=DAYS[3])
    unclassified = make_disclosure(rcept_no=DAYS[3] + "000004", rcept_dt=DAYS[3])
    storage.append_disclosures([keep, correction, other, unclassified], tmp_path)
    storage.append_classifications(
        [
            make_classification(rcept_no=keep.rcept_no),
            make_classification(rcept_no=correction.rcept_no),
            make_classification(rcept_no=other.rcept_no, type="기타"),
        ],
        tmp_path,
    )
    events = backtest.run_backtest(tmp_path)
    assert [e.rcept_no for e in events] == [keep.rcept_no]
    saved = (tmp_path / "results" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    assert EventResult.from_dict(json.loads(saved[0])).car[1] == pytest.approx(0.02)
