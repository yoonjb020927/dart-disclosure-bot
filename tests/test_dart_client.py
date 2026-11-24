import io
import json
import zipfile

import pytest

from dartbot.dart_client import DartApiError, DartClient


class FakeResponse:
    def __init__(self, payload=None, content=None, status_code=200):
        self._payload = payload
        self.content = content if content is not None else json.dumps(payload).encode()
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def row(n):
    return {"rcept_no": f"2026112000000{n}", "report_nm": f"공시{n}", "corp_cls": "Y"}


def make_zip(text: str, encoding: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20261120000001.xml", text.encode(encoding))
    return buf.getvalue()


def test_list_paginates_until_total_page():
    session = FakeSession(
        [
            FakeResponse({"status": "000", "total_page": 2, "list": [row(1), row(2)]}),
            FakeResponse({"status": "000", "total_page": 2, "list": [row(3)]}),
        ]
    )
    rows = DartClient(api_key="k", session=session).list_disclosures("20261120", "Y", "B")
    assert len(rows) == 3
    assert [c[1]["page_no"] for c in session.calls] == [1, 2]
    assert session.calls[0][1]["bgn_de"] == "20261120" == session.calls[0][1]["end_de"]
    assert session.calls[0][1]["page_count"] == 100


def test_list_status_013_returns_empty():
    session = FakeSession([FakeResponse({"status": "013", "message": "조회된 데이타가 없습니다."})])
    assert DartClient(api_key="k", session=session).list_disclosures("20261122", "Y", "B") == []


def test_list_status_020_raises():
    session = FakeSession([FakeResponse({"status": "020", "message": "요청 제한을 초과하였습니다."})])
    with pytest.raises(DartApiError, match="020"):
        DartClient(api_key="k", session=session).list_disclosures("20261120", "Y", "B")


def test_document_text_strips_tags_and_truncates():
    xml = "<DOCUMENT><P>유상증자   결정</P><TABLE><TD>신주 1,000,000주</TD></TABLE></DOCUMENT>"
    session = FakeSession([FakeResponse(content=make_zip(xml, "utf-8"))])
    text = DartClient(api_key="k", session=session).document_text("20261120000001", max_chars=12)
    assert "<" not in text
    assert text.startswith("유상증자 결정")
    assert len(text) <= 12


def test_document_text_cp949_fallback():
    xml = "<P>자기주식 취득 결정</P>"
    session = FakeSession([FakeResponse(content=make_zip(xml, "cp949"))])
    text = DartClient(api_key="k", session=session).document_text("20261120000001", max_chars=100)
    assert text == "자기주식 취득 결정"


def test_document_error_json_raises():
    session = FakeSession([FakeResponse({"status": "014", "message": "파일이 존재하지 않습니다."})])
    with pytest.raises(DartApiError, match="014"):
        DartClient(api_key="k", session=session).document_text("x", max_chars=100)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(DartApiError, match="DART_API_KEY"):
        DartClient()


def test_network_error_retries_then_raises(monkeypatch):
    import requests

    class Boom:
        calls = 0

        def get(self, *a, **k):
            Boom.calls += 1
            raise requests.ConnectionError("down")

    monkeypatch.setattr("dartbot.dart_client.time.sleep", lambda s: None)
    with pytest.raises(DartApiError):
        DartClient(api_key="k", session=Boom()).list_disclosures("20261120", "Y", "B")
    assert Boom.calls == 3


def test_document_error_carries_status():
    session = FakeSession([FakeResponse({"status": "014", "message": "파일이 존재하지 않습니다."})])
    with pytest.raises(DartApiError) as info:
        DartClient(api_key="k", session=session).document_text("x", max_chars=100)
    assert info.value.status == "014"
