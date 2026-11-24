"""Settings in one place. Values marked (probe) are confirmed against real APIs."""
from __future__ import annotations

from pathlib import Path

# --- 분류 체계 ---------------------------------------------------------------
TYPES: tuple[str, ...] = (
    "유상증자",
    "무상증자",
    "자기주식 취득",
    "자기주식 처분",
    "자기주식 소각",
    "단일판매·공급계약",
    "최대주주 변경",
    "전환사채·신주인수권부사채 발행",
    "합병·분할",
    "영업(잠정)실적",
    "기타",
)
SENTIMENTS: tuple[str, ...] = ("긍정", "부정", "중립")
ORIGINS: tuple[str, ...] = ("live", "backfill")
INPUT_MODES: tuple[str, ...] = ("body", "title_only")
EVENT_STATUSES: tuple[str, ...] = ("ok", "pending", "no_price")

# --- 수집 대상 -----------------------------------------------------------------
MARKETS: tuple[str, ...] = ("Y", "K")  # 유가증권, 코스닥
PBLNTF_TYPES: tuple[str, ...] = ("B", "I")  # 주요사항보고, 거래소공시

# --- 백테스트 -------------------------------------------------------------------
CAR_WINDOWS: tuple[int, ...] = (1, 5, 20)
PRIMARY_WINDOW = 1
PRIMARY_THRESHOLD = 0.01
THRESHOLDS: tuple[float, ...] = (0.005, 0.01, 0.02)
MIN_SAMPLE = 30
PRICE_LOOKBACK_DAYS = 40

# --- LLM -------------------------------------------------------------------------
# Pinned model name (no -latest alias). Confirm the free-tier model with
# `python -m dartbot probe gemini` and adjust limits to <=80% of the real quota.
GEMINI_MODEL = "gemini-2.5-flash"
BATCH_SIZE = 10
REQUESTS_PER_MINUTE = 10
DAILY_REQUEST_CAP = 200
BODY_MAX_CHARS = 4000

# --- 운영 -------------------------------------------------------------------------
# Day the scheduled daily run was switched on. Disclosures on/after it are "live".
# Placeholder until go-live (README: 운영 시작).
LIVE_START_DATE = "99991231"
BACKFILL_START = "20251124"
DATA_DIR = Path("data")
SITE_DIR = Path("site")
TIMEZONE = "Asia/Seoul"
