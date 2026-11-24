"""Decide which filings matter: listed market, candidate type, correction flag."""
from __future__ import annotations

import re

from . import config
from .models import Disclosure

_LEADING_BRACKETS = re.compile(r"^(\[[^\]]*\])+")


def normalize_title(report_nm: str) -> str:
    title = re.sub(r"\s+", "", report_nm).replace("ㆍ", "·")
    return _LEADING_BRACKETS.sub("", title)


def is_correction(report_nm: str) -> bool:
    return report_nm.strip().startswith(config.CORRECTION_PREFIXES)


def candidate_type(report_nm: str) -> str | None:
    title = normalize_title(report_nm)
    for keyword, type_ in config.TITLE_RULES:
        if keyword in title:
            return type_
    return None


def to_disclosure(row: dict) -> Disclosure | None:
    """API row -> Disclosure, or None if not a KOSPI/KOSDAQ listed company."""
    stock_code = (row.get("stock_code") or "").strip()
    if row.get("corp_cls") not in config.MARKETS or not stock_code:
        return None
    report_nm = row["report_nm"].strip()
    return Disclosure(
        rcept_no=row["rcept_no"],
        rcept_dt=row["rcept_dt"],
        corp_code=row["corp_code"],
        corp_name=row["corp_name"],
        stock_code=stock_code,
        corp_cls=row["corp_cls"],
        report_nm=report_nm,
        is_correction=is_correction(report_nm),
        candidate_type=candidate_type(report_nm),
    )
