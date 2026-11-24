import pytest

from dartbot import prices


def stock_row(code, close, fluc, name="종목"):
    return {"BAS_DD": "", "ISU_CD": code, "ISU_NM": name, "TDD_CLSPRC": close, "FLUC_RT": fluc}


def index_row(name, close, fluc):
    return {"BAS_DD": "", "IDX_NM": name, "CLSPRC_IDX": close, "FLUC_RT": fluc}


class FakeKrx:
    """data[date][kind] -> rows; missing date means holiday (all kinds empty)."""

    def __init__(self, data):
        self.data = data
        self.calls = []

    def fetch(self, kind, date):
        self.calls.append((kind, date))
        return self.data.get(date, {}).get(kind, [])


def day(stk=(), ksq=(), kospi=0.0, kosdaq=0.0):
    return {
        "stk": list(stk),
        "ksq": list(ksq),
        "kospi_idx": [index_row("코스피", "2,500.00", str(kospi)), index_row("코스피 200", "330.00", "9.9")],
        "kosdaq_idx": [index_row("코스닥", "700.00", str(kosdaq)), index_row("코스닥 150", "1,200", "9.9")],
    }


def test_download_day_holiday_writes_nothing(tmp_path):
    assert prices.download_day(FakeKrx({}), "20261122", tmp_path) is False
    assert prices.trading_days(tmp_path) == []


def test_download_day_skips_existing_files(tmp_path):
    krx = FakeKrx({"20261120": day(stk=[stock_row("005930", "71,000", "1.00")])})
    assert prices.download_day(krx, "20261120", tmp_path)
    n = len(krx.calls)
    assert prices.download_day(krx, "20261120", tmp_path)
    assert len(krx.calls) == n


def test_ret_uses_fluc_rt_not_close_diff(tmp_path):
    # 무상증자 권리락: close halves but KRX's adjusted change is +2%
    krx = FakeKrx(
        {
            "20261119": day(stk=[stock_row("111111", "10,000", "0.00")]),
            "20261120": day(stk=[stock_row("111111", "5,000", "2.00")]),
        }
    )
    prices.download_range(krx, "20261119", "20261120", tmp_path)
    assert prices.stock_returns(tmp_path, "111111", ["20261120"]) == [pytest.approx(0.02)]


def test_index_rows_filtered_to_kospi_kosdaq(tmp_path):
    prices.download_day(FakeKrx({"20261120": day(stk=[stock_row("005930", "71,000", "1.00")], kospi=-1.5, kosdaq=0.5)}), "20261120", tmp_path)
    assert prices.market_returns(tmp_path, "Y", ["20261120"]) == [pytest.approx(-0.015)]
    assert prices.market_returns(tmp_path, "K", ["20261120"]) == [pytest.approx(0.005)]


def test_kosdaq_stocks_saved_with_market_k(tmp_path):
    prices.download_day(FakeKrx({"20261120": day(ksq=[stock_row("222222", "5,000", "-3.00")])}), "20261120", tmp_path)
    assert prices.stock_returns(tmp_path, "222222", ["20261120"]) == [pytest.approx(-0.03)]


def test_stock_returns_missing_code_gives_none(tmp_path):
    prices.download_day(FakeKrx({"20261120": day(stk=[stock_row("005930", "71,000", "1.00")])}), "20261120", tmp_path)
    assert prices.stock_returns(tmp_path, "999999", ["20261120", "20261121"]) == [None, None]


def test_download_range_skips_weekends_and_counts_new(tmp_path):
    krx = FakeKrx({d: day(stk=[stock_row("005930", "1", "0")]) for d in ("20261120", "20261123")})
    assert prices.download_range(krx, "20261120", "20261123", tmp_path) == 2
    assert all(date not in ("20261121", "20261122") for _, date in krx.calls)


def test_trading_days_sorted(tmp_path):
    krx = FakeKrx({d: day(stk=[stock_row("005930", "1", "0")]) for d in ("20261123", "20261120")})
    prices.download_range(krx, "20261120", "20261123", tmp_path)
    assert prices.trading_days(tmp_path) == ["20261120", "20261123"]


def test_zero_volume_halted_stock_has_no_return(tmp_path):
    halted = {**stock_row("000300", "4,200", "0.00"), "ACC_TRDVOL": "0"}
    traded = {**stock_row("005930", "71,000", "1.00"), "ACC_TRDVOL": "1,234"}
    prices.download_day(FakeKrx({"20261120": day(stk=[halted, traded])}), "20261120", tmp_path)
    assert prices.stock_returns(tmp_path, "000300", ["20261120"]) == [None]
    assert prices.stock_returns(tmp_path, "005930", ["20261120"]) == [pytest.approx(0.01)]


def test_partial_day_without_index_writes_nothing(tmp_path):
    partial = {**day(stk=[stock_row("005930", "71,000", "1.00")]), "kosdaq_idx": []}
    assert prices.download_day(FakeKrx({"20261120": partial}), "20261120", tmp_path) is False
    assert prices.trading_days(tmp_path) == []


def test_download_range_repairs_missing_index_file(tmp_path):
    krx = FakeKrx({"20261120": day(stk=[stock_row("005930", "71,000", "1.00")])})
    prices.download_day(krx, "20261120", tmp_path)
    (tmp_path / "prices" / "index" / "2026" / "20261120.csv.gz").unlink()
    prices.download_range(krx, "20261120", "20261120", tmp_path)
    assert (tmp_path / "prices" / "index" / "2026" / "20261120.csv.gz").exists()
