import pytest

from dartbot.filters import candidate_type, is_correction, normalize_title, to_disclosure


@pytest.mark.parametrize(
    "title, expected",
    [
        ("주요사항보고서(유상증자결정)", "유상증자"),
        ("주요사항보고서(무상증자결정)", "무상증자"),
        ("주요사항보고서(유무상증자결정)", "유상증자"),
        ("단일판매ㆍ공급계약체결", "단일판매·공급계약"),
        ("[기재정정]주요사항보고서(자기주식취득결정)", "자기주식 취득"),
        ("주요사항보고서(자기주식처분결정)", "자기주식 처분"),
        ("주식소각결정", "자기주식 소각"),
        ("최대주주변경을수반하는주식양수도계약체결", "최대주주 변경"),
        ("주요사항보고서(전환사채권발행결정)", "전환사채·신주인수권부사채 발행"),
        ("주요사항보고서(회사분할결정)", "합병·분할"),
        ("영업(잠정)실적(공정공시)", "영업(잠정)실적"),
        ("매출액또는손익구조30%(대규모법인은15%)이상변경", "영업(잠정)실적"),
        ("임원ㆍ주요주주특정증권등소유상황보고서", None),
    ],
)
def test_candidate_type(title, expected):
    assert candidate_type(title) == expected


def test_normalize_title_removes_spaces_prefix_and_unifies_dot():
    assert normalize_title("[기재정정] 단일판매ㆍ공급계약 체결") == "단일판매·공급계약체결"


def test_is_correction():
    assert is_correction("[기재정정]주요사항보고서(자기주식취득결정)")
    assert not is_correction("주요사항보고서(자기주식취득결정)")


def api_row(**kw):
    base = {
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "corp_cls": "Y",
        "report_nm": "주요사항보고서(자기주식취득결정)",
        "rcept_no": "20261120000123",
        "rcept_dt": "20261120",
    }
    base.update(kw)
    return base


def test_to_disclosure_maps_fields():
    d = to_disclosure(api_row())
    assert d.candidate_type == "자기주식 취득"
    assert d.is_correction is False
    assert d.stock_code == "005930"


def test_to_disclosure_drops_konex_and_unlisted():
    assert to_disclosure(api_row(corp_cls="N")) is None
    assert to_disclosure(api_row(stock_code="")) is None
    assert to_disclosure(api_row(stock_code=" ")) is None


def test_to_disclosure_keeps_non_candidate():
    d = to_disclosure(api_row(report_nm="임원ㆍ주요주주특정증권등소유상황보고서"))
    assert d is not None and d.candidate_type is None
