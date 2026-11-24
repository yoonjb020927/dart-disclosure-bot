import pytest

from dartbot.masking import mask_text

NAME = "에코프로비엠"
CODE = "247540"


@pytest.mark.parametrize(
    "variant",
    ["(주)에코프로비엠", "에코프로비엠(주)", "주식회사 에코프로비엠", "㈜에코프로비엠", "에코프로비엠"],
)
def test_masks_company_variants(variant):
    out = mask_text(f"{variant}는 신규 계약을 체결했다.", NAME, CODE)
    assert out == "A사는 신규 계약을 체결했다."


@pytest.mark.parametrize(
    "date_text",
    ["2026-11-20", "2026.11.20", "2026/11/20", "2026년 11월 20일", "20261120", "2026. 11. 20"],
)
def test_masks_dates_all_formats(date_text):
    assert mask_text(f"계약일 {date_text} 기준", NAME, CODE) == "계약일 [날짜] 기준"


def test_keeps_amounts_and_ratios():
    text = "계약금액 1,234억원, 매출 대비 15.3%, 1,000,000주"
    assert mask_text(text, NAME, CODE) == text


def test_masks_stock_code():
    assert mask_text("종목코드 247540 상장", NAME, CODE) == "종목코드 [코드] 상장"


def test_masks_other_six_digit_codes():
    assert mask_text("자회사 123456 지분", NAME, CODE) == "자회사 [코드] 지분"
