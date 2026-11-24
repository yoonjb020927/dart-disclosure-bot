import pytest
import requests

from dartbot.krx_client import KrxApiError, KrxClient


class Resp:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers, params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_fetch_uses_auth_header_and_basDd():
    s = Session([Resp({"OutBlock_1": [{"ISU_CD": "005930"}]})])
    rows = KrxClient(api_key="key", session=s).fetch("stk", "20261120")
    url, headers, params = s.calls[0]
    assert url.endswith("/sto/stk_bydd_trd")
    assert headers == {"AUTH_KEY": "key"}
    assert params == {"basDd": "20261120"}
    assert rows == [{"ISU_CD": "005930"}]


def test_401_raises_with_service_hint():
    s = Session([Resp({}, status_code=401)])
    with pytest.raises(KrxApiError, match="서비스 이용 신청"):
        KrxClient(api_key="key", session=s).fetch("kospi_idx", "20261120")


def test_retries_then_raises(monkeypatch):
    monkeypatch.setattr("dartbot.krx_client.time.sleep", lambda s: None)
    s = Session([requests.ConnectionError("x")] * 3)
    with pytest.raises(KrxApiError):
        KrxClient(api_key="key", session=s).fetch("stk", "20261120")
    assert len(s.calls) == 3


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        KrxClient(api_key="key", session=Session([])).fetch("etf", "20261120")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    with pytest.raises(KrxApiError, match="KRX_API_KEY"):
        KrxClient()
