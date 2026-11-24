import json

import pytest

from dartbot.models import Classification, Disclosure, EventResult


def make_disclosure(**kw):
    base = dict(
        rcept_no="20261120000123",
        rcept_dt="20261120",
        corp_code="00126380",
        corp_name="삼성전자",
        stock_code="005930",
        corp_cls="Y",
        report_nm="주요사항보고서(자기주식취득결정)",
        is_correction=False,
        candidate_type="자기주식 취득",
    )
    base.update(kw)
    return Disclosure(**base)


def make_classification(**kw):
    base = dict(
        rcept_no="20261120000123",
        summary=("첫째.", "둘째.", "셋째."),
        type="자기주식 취득",
        sentiment="긍정",
        confidence=0.8,
        rationale="주주환원",
        classifier_version="m+p1",
        origin="live",
        input_mode="body",
        classified_at="2026-11-21T07:00:00+09:00",
    )
    base.update(kw)
    return Classification(**base)


def test_disclosure_roundtrip():
    d = make_disclosure()
    assert Disclosure.from_dict(json.loads(json.dumps(d.to_dict()))) == d


def test_classification_roundtrip_keeps_summary_tuple():
    c = make_classification()
    assert Classification.from_dict(json.loads(json.dumps(c.to_dict()))) == c


def test_classification_rejects_unknown_type():
    with pytest.raises(ValueError):
        make_classification(type="배당")


def test_classification_rejects_bad_sentiment():
    with pytest.raises(ValueError):
        make_classification(sentiment="매우긍정")


def test_classification_rejects_confidence_out_of_range():
    with pytest.raises(ValueError):
        make_classification(confidence=1.5)


def test_event_result_car_keys_roundtrip_as_int():
    e = EventResult(rcept_no="1", t0="20261120", car={1: 0.01, 5: None, 20: None}, status="ok", source="krx")
    back = EventResult.from_dict(json.loads(json.dumps(e.to_dict())))
    assert back == e
    assert set(back.car) == {1, 5, 20}


def test_event_result_rejects_bad_status():
    with pytest.raises(ValueError):
        EventResult(rcept_no="1", t0=None, car={}, status="weird", source="krx")
