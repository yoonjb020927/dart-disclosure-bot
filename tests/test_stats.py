import pytest

from dartbot.models import EventResult
from dartbot.stats import summarize
from tests.test_models import make_classification

NOW = "2026-11-24T07:00:00+09:00"


def ev(n, car1, status="ok"):
    return EventResult(f"r{n}", "20261120", {1: car1, 5: car1, 20: None}, status, "krx")


def cl(n, sentiment="긍정", origin="live", version="v1", type_="유상증자", confidence=0.8):
    return make_classification(
        rcept_no=f"r{n}", sentiment=sentiment, origin=origin, classifier_version=version,
        type=type_, confidence=confidence,
    )


def group(summary, origin="live", version="v1"):
    return next(g for g in summary["groups"] if g["origin"] == origin and g["classifier_version"] == version)


def test_groups_split_by_origin_and_version():
    s = summarize([cl(1), cl(2, origin="backfill"), cl(3, version="v2")], [ev(1, 0.02), ev(2, 0.02), ev(3, 0.02)], NOW)
    keys = {(g["origin"], g["classifier_version"]) for g in s["groups"]}
    assert keys == {("live", "v1"), ("backfill", "v1"), ("live", "v2")}
    assert s["generated_at"] == NOW


def test_insufficient_flag_below_30():
    s29 = summarize([cl(i) for i in range(29)], [ev(i, 0.02) for i in range(29)], NOW)
    s30 = summarize([cl(i) for i in range(30)], [ev(i, 0.02) for i in range(30)], NOW)
    assert group(s29)["by_sentiment"]["긍정"]["1"]["insufficient"] is True
    assert group(s30)["by_sentiment"]["긍정"]["1"]["insufficient"] is False
    assert group(s30)["by_type"]["유상증자"]["insufficient"] is False


def test_confusion_counts():
    cls = [cl(1, "긍정"), cl(2, "긍정"), cl(3, "부정"), cl(4, "중립")]
    evs = [ev(1, 0.05), ev(2, -0.05), ev(3, -0.05), ev(4, 0.0)]
    c = group(summarize(cls, evs, NOW))["confusion"]
    assert c["긍정"] == {"긍정": 1, "부정": 1, "중립": 0}
    assert c["부정"]["부정"] == 1 and c["중립"]["중립"] == 1


def test_directional_hit_excludes_neutral_predictions():
    cls = [cl(1, "긍정"), cl(2, "부정"), cl(3, "중립")]
    evs = [ev(1, 0.003), ev(2, 0.004), ev(3, 0.5)]
    assert group(summarize(cls, evs, NOW))["directional_hit_rate"] == pytest.approx(0.5)


def test_hit_rate_by_threshold():
    cls = [cl(1, "긍정"), cl(2, "긍정")]
    evs = [ev(1, 0.008), ev(2, 0.03)]
    h = group(summarize(cls, evs, NOW))["hit_rate_by_threshold"]
    assert h == {"0.005": 1.0, "0.01": 0.5, "0.02": 0.5}


def test_pvalue_none_for_single_sample():
    g = group(summarize([cl(1)], [ev(1, 0.02)], NOW))
    assert g["by_sentiment"]["긍정"]["1"]["p_value"] is None
    assert g["by_sentiment"]["부정"]["1"]["n"] == 0


def test_pvalue_none_for_identical_values():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        g = group(summarize([cl(i) for i in range(5)], [ev(i, 0.02) for i in range(5)], NOW))
    assert g["by_sentiment"]["긍정"]["1"]["p_value"] is None


def test_pvalue_present_for_many_samples():
    cls = [cl(i) for i in range(10)]
    evs = [ev(i, 0.02 + 0.001 * i) for i in range(10)]
    p = group(summarize(cls, evs, NOW))["by_sentiment"]["긍정"]["1"]["p_value"]
    assert p is not None and p < 0.05


def test_excludes_pending_and_no_price():
    cls = [cl(1), cl(2), cl(3)]
    evs = [ev(1, 0.02), ev(2, None, "pending"), ev(3, None, "no_price")]
    g = group(summarize(cls, evs, NOW))
    assert (g["n_ok"], g["n_pending"], g["n_no_price"]) == (1, 1, 1)
    assert g["by_sentiment"]["긍정"]["1"]["n"] == 1


def test_confidence_buckets_edges():
    cls = [cl(1, confidence=0.5), cl(2, confidence=1.0)]
    evs = [ev(1, 0.02), ev(2, -0.02)]
    b = group(summarize(cls, evs, NOW))["hit_rate_by_confidence"]
    assert b["0.5-0.7"] == 1.0 and b["0.9-1.0"] == 0.0 and b["0.0-0.5"] is None


def test_other_type_excluded_per_classification():
    s = summarize([cl(1, version="v1", type_="기타"), cl(1, version="v2")], [ev(1, 0.02)], NOW)
    assert {(g["origin"], g["classifier_version"]) for g in s["groups"]} == {("live", "v2")}
