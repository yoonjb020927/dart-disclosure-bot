import json

import pytest

from dartbot import config
from dartbot.llm.base import ClassifierInput, QuotaExceeded
from dartbot.llm.gemini import GeminiClassifier
from dartbot.llm.prompt import PROMPT_VERSION, build_prompt


def item(n):
    return ClassifierInput(rcept_no=f"r{n}", title=f"A사 공시{n}", body=f"A사 본문{n}")


def good(n, **kw):
    out = {
        "rcept_no": f"r{n}",
        "summary": ["하나.", "둘.", "셋."],
        "type": "유상증자",
        "sentiment": "부정",
        "confidence": 0.7,
        "rationale": "희석",
    }
    out.update(kw)
    return out


class Resp:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Resp(reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False))


class FakeClient:
    def __init__(self, replies):
        self.models = FakeModels(replies)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make(replies, clock=None):
    clock = clock or FakeClock()
    client = FakeClient(replies)
    clf = GeminiClassifier(api_key="k", model="gm", client=client, sleep=clock.sleep, clock=clock.time)
    return clf, client


def test_prompt_lists_all_types_and_rcept_nos():
    prompt = build_prompt([item(1), item(2)])
    for t in config.TYPES:
        assert t in prompt
    assert "r1" in prompt and "r2" in prompt


def test_prompt_keeps_masked_tokens():
    assert "A사 본문1" in build_prompt([item(1)])


def test_batch_success_maps_by_rcept_no():
    clf, client = make([[good(2), good(1, sentiment="긍정")]])
    ok, failed = clf.classify_batch([item(1), item(2)])
    assert failed == []
    by_id = {o.rcept_no: o for o in ok}
    assert by_id["r1"].sentiment == "긍정"
    assert by_id["r2"].summary == ("하나.", "둘.", "셋.")


def test_invalid_enum_retried_singly_then_failed():
    clf, client = make([[good(1), good(2, type="배당"), good(3)], [good(2, type="배당")]])
    ok, failed = clf.classify_batch([item(1), item(2), item(3)])
    assert sorted(o.rcept_no for o in ok) == ["r1", "r3"]
    assert failed == ["r2"]
    assert len(client.models.prompts) == 2


def test_missing_item_retried_singly_and_recovered():
    clf, _ = make([[good(1)], [good(2)]])
    ok, failed = clf.classify_batch([item(1), item(2)])
    assert sorted(o.rcept_no for o in ok) == ["r1", "r2"] and failed == []


def test_bad_summary_length_is_failure():
    clf, _ = make([[good(1, summary=["하나."])], [good(1, summary=["하나."])]])
    ok, failed = clf.classify_batch([item(1)])
    assert ok == [] and failed == ["r1"]


def test_malformed_json_retries_all_singly():
    clf, client = make(["{not json", [good(1)], [good(2)], [good(3)]])
    ok, failed = clf.classify_batch([item(1), item(2), item(3)])
    assert len(ok) == 3 and failed == []
    assert len(client.models.prompts) == 4


def test_server_error_on_single_item_marks_failed():
    clf, _ = make([RuntimeError("500 internal")])
    ok, failed = clf.classify_batch([item(1)])
    assert ok == [] and failed == ["r1"]


def test_quota_error_raises_quota_exceeded():
    class Quota(Exception):
        code = 429

    clf, _ = make([Quota("429 RESOURCE_EXHAUSTED")])
    with pytest.raises(QuotaExceeded):
        clf.classify_batch([item(1)])


def test_rate_limit_sleeps_between_calls():
    clock = FakeClock()
    clf, _ = make([[good(1)], [good(2)]], clock=clock)
    clf.classify_batch([item(1)])
    clf.classify_batch([item(2)])
    assert clock.slept == [pytest.approx(60 / config.REQUESTS_PER_MINUTE)]


def test_version_string():
    clf, _ = make([])
    assert clf.version == f"gm+{PROMPT_VERSION}"
