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

CORRECTION_PREFIXES: tuple[str, ...] = ("[기재정정]", "[첨부정정]", "[첨부추가]", "[변경등록]", "[연장결정]")

# (keyword in normalized title, type). Order matters: first match wins.
# 유무상증자결정 contains 무상증자결정, so it must be checked first.
TITLE_RULES: tuple[tuple[str, str], ...] = (
    ("유무상증자결정", "유상증자"),
    ("무상증자결정", "무상증자"),
    ("유상증자결정", "유상증자"),
    ("주식소각결정", "자기주식 소각"),
    ("자기주식취득신탁계약체결결정", "자기주식 취득"),
    ("자기주식취득결정", "자기주식 취득"),
    ("자기주식처분결정", "자기주식 처분"),
    ("단일판매·공급계약체결", "단일판매·공급계약"),
    ("최대주주변경", "최대주주 변경"),
    ("전환사채권발행결정", "전환사채·신주인수권부사채 발행"),
    ("신주인수권부사채권발행결정", "전환사채·신주인수권부사채 발행"),
    ("회사분할합병결정", "합병·분할"),
    ("회사합병결정", "합병·분할"),
    ("회사분할결정", "합병·분할"),
    ("영업(잠정)실적", "영업(잠정)실적"),
    ("매출액또는손익구조", "영업(잠정)실적"),
)

# --- KRX Open API (same key/host as krx-daily-report) -------------------------------
# Endpoint and field names: confirm with `python -m dartbot probe krx` (probe).
KRX_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
KRX_AUTH_HEADER = "AUTH_KEY"
KRX_ROWS_KEY = "OutBlock_1"
KRX_ENDPOINTS = {
    "stk": "sto/stk_bydd_trd",  # 유가증권 일별매매정보
    "ksq": "sto/ksq_bydd_trd",  # 코스닥 일별매매정보
    "kospi_idx": "idx/kospi_dd_trd",  # KOSPI 시리즈 일별시세
    "kosdaq_idx": "idx/kosdaq_dd_trd",  # KOSDAQ 시리즈 일별시세
}
KRX_STOCK_FIELDS = {"code": "ISU_CD", "name": "ISU_NM", "close": "TDD_CLSPRC", "fluc": "FLUC_RT", "volume": "ACC_TRDVOL"}
KRX_INDEX_FIELDS = {"name": "IDX_NM", "close": "CLSPRC_IDX", "fluc": "FLUC_RT"}
# kind -> (index name in the response, name we store)
KRX_INDEX_NAMES = {"kospi_idx": ("코스피", "KOSPI"), "kosdaq_idx": ("코스닥", "KOSDAQ")}
MARKET_INDEX = {"Y": "KOSPI", "K": "KOSDAQ"}

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
GEMINI_MODEL = "gemini-3.5-flash-lite"  # flash free tier = 20 req/day/model; lite has its own quota
BATCH_SIZE = 10
REQUESTS_PER_MINUTE = 10
MAX_FAILED_BATCHES_IN_A_ROW = 3
# daily.yml gives the run step 100 min; 503 backoffs can eat it, so stop classifying at 70
CLASSIFY_TIME_BUDGET_SEC = 70 * 60
GEMINI_TRANSIENT_RETRIES = 3  # 503 overloaded: retry the same call after 20s, 40s, 80s
GEMINI_BACKOFF_SEC = 20  # provider outage: stop instead of burning the day
DAILY_REQUEST_CAP = 200
BODY_MAX_CHARS = 4000

# --- 운영 -------------------------------------------------------------------------
# Day the scheduled daily run was switched on. Disclosures on/after it are "live".
# Placeholder until go-live (README: 운영 시작).
LIVE_START_DATE = "20261124"  # go-live: filings from this date are classified before outcomes exist
BACKFILL_START = "20251124"
DATA_DIR = Path("data")
SITE_DIR = Path("site")
TIMEZONE = "Asia/Seoul"
