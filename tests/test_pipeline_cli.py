from datetime import date

import pytest

from dartbot import __main__ as cli
from dartbot import config, pipeline, storage
from tests.test_classify_runner import FakeClassifier, FakeDart

TODAY = date(2026, 11, 24)  # Tuesday


class ListingDart(FakeDart):
    """One 자기주식취득결정 filing per (day, market) for 'B'; nothing for 'I'."""

    def __init__(self):
        super().__init__()
        self.days = []

    def list_disclosures(self, d, corp_cls, pblntf_ty):
        self.days.append(d)
        if pblntf_ty != "B":
            return []
        return [
            {
                "rcept_no": f"{d}{'1' if corp_cls == 'Y' else '2'}00001",
                "rcept_dt": d,
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "stock_code": "005930" if corp_cls == "Y" else "035720",
                "corp_cls": corp_cls,
                "report_nm": "주요사항보고서(자기주식취득결정)",
            },
            {
                "rcept_no": f"{d}{'1' if corp_cls == 'Y' else '2'}00002",
                "rcept_dt": d,
                "corp_code": "1",
                "corp_name": "비상장",
                "stock_code": "",
                "corp_cls": "E",
                "report_nm": "기타",
            },
        ]


class EmptyKrx:
    def fetch(self, kind, d):
        return []


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LIVE_START_DATE", "20261101")
    monkeypatch.setattr(config, "SITE_DIR", tmp_path / "site")


def run_daily(root, dart=None, clf=None):
    return pipeline.daily(root, TODAY, dart or ListingDart(), EmptyKrx(), clf or FakeClassifier())


def test_daily_catches_up_missed_days(tmp_path):
    storage.write_state(tmp_path, {"last_collected_date": "20261121"})
    dart = ListingDart()
    run_daily(tmp_path, dart)
    assert sorted(set(dart.days)) == ["20261122", "20261123"]
    assert storage.read_state(tmp_path)["last_collected_date"] == "20261123"


def test_daily_first_run_collects_yesterday_only(tmp_path):
    dart = ListingDart()
    result = run_daily(tmp_path, dart)
    assert set(dart.days) == {"20261123"}
    assert result["collect"]["candidates"] == 2
    assert len(storage.load_disclosures(tmp_path)) == 2  # unlisted row dropped
    assert (tmp_path / "results" / "summary.json").exists()
    assert (config.SITE_DIR / "index.html").exists()


def test_daily_classifies_and_logs_run(tmp_path):
    result = run_daily(tmp_path)
    assert result["classify"]["classified"] == 2
    runs = [r for r in storage.load_ops_log(tmp_path) if r["kind"] == "run"]
    assert runs[-1]["classified"] == 2


def test_backfill_does_not_move_state(tmp_path):
    storage.write_state(tmp_path, {"last_collected_date": "20261123"})
    pipeline.backfill(tmp_path, "20250101", "20250103", ListingDart(), EmptyKrx())
    assert storage.read_state(tmp_path)["last_collected_date"] == "20261123"
    assert {d.rcept_dt for d in storage.load_disclosures(tmp_path)} == {"20250101", "20250102", "20250103"}


def test_rerun_same_day_no_duplicates(tmp_path):
    run_daily(tmp_path)
    storage.write_state(tmp_path, {"last_collected_date": "20261122"})  # force re-collecting 20261123
    run_daily(tmp_path)
    assert len(storage.load_disclosures(tmp_path)) == 2
    assert len(storage.load_classifications(tmp_path)) == 2


def test_daily_quota_stop_is_not_failure(tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    monkeypatch.setattr(
        cli, "build_clients", lambda needs: (ListingDart(), EmptyKrx(), FakeClassifier(quota_on_call=1))
    )
    code = cli.main(["daily", "--date", "20261124", "--data", str(tmp_path)])
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "status=ok" in text and "date=20261123" in text


def test_cli_missing_key_exits_2_with_message(tmp_path, monkeypatch, capsys):
    for key in ("DART_API_KEY", "GEMINI_API_KEY", "KRX_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    code = cli.main(["daily", "--data", str(tmp_path)])
    assert code == 2
    assert "DART_API_KEY" in capsys.readouterr().err


def test_cli_backtest_and_site_need_no_keys(tmp_path, monkeypatch):
    for key in ("DART_API_KEY", "GEMINI_API_KEY", "KRX_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    assert cli.main(["backtest", "--data", str(tmp_path)]) == 0
    assert cli.main(["site", "--data", str(tmp_path)]) == 0


class RecordingKrx(EmptyKrx):
    def __init__(self):
        self.days = set()

    def fetch(self, kind, d):
        self.days.add(d)
        return []


def test_daily_refetches_prices_back_to_oldest_filing(tmp_path):
    # prices live in the Actions cache, not git; a lost cache must be rebuilt for every stored filing
    from tests.test_models import make_disclosure

    storage.append_disclosures([make_disclosure(rcept_no="20260302000001", rcept_dt="20260302")], tmp_path)
    storage.write_state(tmp_path, {"last_collected_date": "20261123"})
    krx = RecordingKrx()
    pipeline.daily(tmp_path, TODAY, ListingDart(), krx, FakeClassifier())
    assert min(krx.days) <= "20260302"
    assert "20260302" in krx.days
