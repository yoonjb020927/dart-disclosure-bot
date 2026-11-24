"""Hide company identity and dates from LLM input.

The model may remember what happened to a named company after a given date
(look-ahead). Masking makes it judge the filing's content only, and is applied
identically to live and backfill so both groups share one classifier.
"""
from __future__ import annotations

import re

COMPANY_TOKEN = "A사"
CODE_TOKEN = "[코드]"
DATE_TOKEN = "[날짜]"

_DATE_PATTERNS = (
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"(?<!\d)\d{4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)"),
)
# Six digits standing alone, not part of a number with separators or a unit.
_CODE = re.compile(r"(?<![\d,.])\d{6}(?![\d,.])(?!\s*(?:원|주|%|천|만|억))")
_CORP_PREFIX = r"(?:주식회사\s*|\(주\)\s*|㈜\s*)?"
_CORP_SUFFIX = r"(?:\s*\(주\)|\s*㈜|\s*주식회사)?"


def mask_text(text: str, corp_name: str, stock_code: str) -> str:
    if corp_name:
        pattern = _CORP_PREFIX + re.escape(corp_name.strip()) + _CORP_SUFFIX
        text = re.sub(pattern, COMPANY_TOKEN, text)
    for date_pattern in _DATE_PATTERNS:
        text = date_pattern.sub(DATE_TOKEN, text)
    if stock_code:
        text = text.replace(stock_code, CODE_TOKEN)
    return _CODE.sub(CODE_TOKEN, text)
