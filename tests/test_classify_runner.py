from datetime import datetime

import pytest

from dartbot import classify_runner as cr
from dartbot import config, storage
from dartbot.dart_client import DartApiError
from dartbot.llm.base import ClassifierOutput, QuotaExceeded
from tests.test_models import make_classification, make_disclosure

NOW = lambda: datetime(2026, 11, 24, 7, 0)  # noqa: E731


@pytest.fixture(autouse=True)
def live_from_nov(monkeypatch):
    monkeypatch.setattr(config, "LIVE_START_DATE", "20261101")


def disc(n, dt="20261120", **kw):
    return make_disclosure(rcept_no=f"{dt}{n:06d}", rcept_dt=dt, **kw)


class FakeDart:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def document_text(self, rcept_no, max_chars):
        if rcept_no in self.fail:
            raise DartApiError("014", status="014")
        return "삼성전자는 2026-11-20 자기주식 취득을 결정했다."


class FakeClassifier:
    version = "fake+p1"

    def __init__(self, quota_on_call=None, fail_ids=()):
        self.calls = []
        self.quota_on_call = quota_on_call
        self.fail_ids = set(fail_ids)

    def classify_batch(self, items):
        self.calls.append(items)
        if self.quota_on_call == len(self.calls):
            raise QuotaExceeded("429")
        ok = [
            ClassifierOutput(i.rcept_no, ("a.", "b.", "c."), "자기주식 취득", "긍정", 0.9, "환원")
            for i in items
            if i.rcept_no not in self.fail_ids
        ]
        return ok, [i.rcept_no for i in items if i.rcept_no in self.fail_ids]


def test_origin_of():
    assert cr.origin_of(disc(1, "20261101")) == "live"
    assert cr.origin_of(disc(1, "20261031")) == "backfill"


def test_queue_live_before_backfill_newest_first():
    items = [disc(1, "20260601"), disc(2, "20261105"), disc(3, "20261120"), disc(4, "20260901")]
    got = [d.rcept_dt for d in cr.pending_queue(items, [], "v")]
    assert got == ["20261120", "20261105", "20260901", "20260601"]


def test_queue_skips_corrections_and_non_candidates():
    items = [disc(1), disc(2, is_correction=True), disc(3, candidate_type=None)]
    assert [d.rcept_no for d in cr.pending_queue(items, [], "v")] == [items[0].rcept_no]


def test_queue_skips_already_classified_same_version():
    d = disc(1)
    done = [make_classification(rcept_no=d.rcept_no, classifier_version="v")]
    assert cr.pending_queue([d], done, "v") == []
    assert cr.pending_queue([d], done, "v2") == [d]


def test_body_failure_falls_back_to_title_only(tmp_path):
    d = disc(1)
    storage.append_disclosures([d], tmp_path)
    clf = FakeClassifier()
    cr.run_classification(tmp_path, FakeDart(fail={d.rcept_no}), clf, max_requests=5, now=NOW)
    saved = storage.load_classifications(tmp_path)
    assert saved[0].input_mode == "title_only"
    assert clf.calls[0][0].body == ""


def test_max_requests_caps_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BATCH_SIZE", 10)
    storage.append_disclosures([disc(n) for n in range(25)], tmp_path)
    result = cr.run_classification(tmp_path, FakeDart(), FakeClassifier(), max_requests=2, now=NOW)
    assert result["classified"] == 20
    assert result["remaining"] == 5
    assert result["stopped_by_quota"] is False


def test_quota_stops_and_keeps_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BATCH_SIZE", 10)
    storage.append_disclosures([disc(n) for n in range(25)], tmp_path)
    result = cr.run_classification(
        tmp_path, FakeDart(), FakeClassifier(quota_on_call=2), max_requests=5, now=NOW
    )
    assert result["stopped_by_quota"] is True
    assert result["classified"] == 10
    assert len(storage.load_classifications(tmp_path)) == 10


def test_failed_items_stay_in_queue(tmp_path):
    a, b = disc(1), disc(2)
    storage.append_disclosures([a, b], tmp_path)
    result = cr.run_classification(
        tmp_path, FakeDart(), FakeClassifier(fail_ids={b.rcept_no}), max_requests=5, now=NOW
    )
    assert result["failed"] == 1 and result["remaining"] == 1
    left = cr.pending_queue(storage.load_disclosures(tmp_path), storage.load_classifications(tmp_path), "fake+p1")
    assert [d.rcept_no for d in left] == [b.rcept_no]


def test_masking_applied_before_classify(tmp_path):
    storage.append_disclosures([disc(1, report_nm="삼성전자 자기주식취득결정")], tmp_path)
    clf = FakeClassifier()
    cr.run_classification(tmp_path, FakeDart(), clf, max_requests=5, now=NOW)
    sent = clf.calls[0][0]
    assert "삼성전자" not in sent.title + sent.body
    assert "2026-11-20" not in sent.body


def test_saved_record_fields(tmp_path):
    storage.append_disclosures([disc(1)], tmp_path)
    cr.run_classification(tmp_path, FakeDart(), FakeClassifier(), max_requests=5, now=NOW)
    c = storage.load_classifications(tmp_path)[0]
    assert c.origin == "live" and c.classifier_version == "fake+p1" and c.input_mode == "body"
    assert c.classified_at.startswith("2026-11-24T07:00")


class FlakyDart(FakeDart):
    def __init__(self, status):
        super().__init__()
        self.status = status

    def document_text(self, rcept_no, max_chars):
        raise DartApiError(f"{self.status} error", status=self.status)


def test_transient_dart_error_leaves_item_queued(tmp_path):
    storage.append_disclosures([disc(1)], tmp_path)
    clf = FakeClassifier()
    result = cr.run_classification(tmp_path, FlakyDart(None), clf, max_requests=5, now=NOW)
    assert storage.load_classifications(tmp_path) == []
    assert result["failed"] == 1 and result["remaining"] == 1
    assert clf.calls == []


def test_dart_rate_limit_stops_the_run(tmp_path):
    storage.append_disclosures([disc(n) for n in range(3)], tmp_path)
    result = cr.run_classification(tmp_path, FlakyDart("020"), FakeClassifier(), max_requests=5, now=NOW)
    assert result["stopped_by_quota"] is True and result["classified"] == 0


def test_stops_after_consecutive_failed_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BATCH_SIZE", 10)
    items = [disc(n) for n in range(60)]
    storage.append_disclosures(items, tmp_path)
    clf = FakeClassifier(fail_ids={d.rcept_no for d in items})
    cr.run_classification(tmp_path, FakeDart(), clf, max_requests=6, now=NOW)
    assert len(clf.calls) == config.MAX_FAILED_BATCHES_IN_A_ROW
