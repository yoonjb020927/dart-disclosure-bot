# DART 공시 요약·분류봇 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전날 DART 주요 공시를 Gemini로 요약·분류하고, 공시 후 시장조정 초과수익률로 분류 정확도를 검증해서 GitHub Pages 대시보드로 공개하는 자동화 봇을 만든다. 첫 결과물은 최근 1년 결과다.

**Architecture:**
- Python 패키지 `dartbot` 하나에 기능별 모듈을 둔다. 모든 상태와 결과는 저장소 안의 JSONL·CSV 파일에 둔다.
- GitHub Actions가 매일 수집 → 분류(대기열) → 백테스트 → 정적 사이트 생성 → 커밋 → Pages 배포를 수행한다.
- 과거 1년 치는 수동 backfill 워크플로로 원자료를 채운다. 분류는 매일 실행에서 하루 상한까지 소화한다.

**Tech Stack:**
- Python 3.12
- requests, pandas, numpy, scipy, python-dotenv, tzdata
- google-genai (Gemini)
- Jinja2, Chart.js 4.4.1 (CDN)
- pytest, pytest-cov
- GitHub Actions, GitHub Pages

**Spec:** `docs/superpowers/specs/2026-11-24-dart-disclosure-bot-design.md`

**참고 코드:** `C:\Users\user\Desktop\krx-daily-report`
- `src/krxreport/krx_client.py`
- `.github/workflows/daily-report.yml`, `backfill.yml`, `ci.yml`

패턴만 옮기고, 의존성으로 걸지는 않는다.

## Global Constraints

- 비용 0원: 유료 API, 유료 플랜을 쓰지 않는다.
- 시크릿은 `DART_API_KEY`, `GEMINI_API_KEY`, `KRX_API_KEY` 세 개다.
  - 코드에는 환경변수 이름만 쓴다.
  - 로컬은 `.env`를 쓰고 `.gitignore`에 넣는다.
  - `.env.example`에는 자리표시자만 둔다.
- 대상 시장은 `corp_cls` 기준 `Y`(유가증권)와 `K`(코스닥)뿐이다.
- 공시 유형 enum은 아래 11개를 정확히 쓴다.
  - `유상증자`, `무상증자`, `자기주식 취득`, `자기주식 처분`, `자기주식 소각`
  - `단일판매·공급계약`, `최대주주 변경`, `전환사채·신주인수권부사채 발행`
  - `합병·분할`, `영업(잠정)실적`, `기타`
- 영향 enum은 `긍정`, `부정`, `중립`이다.
- CAR 기간은 [0,+1], [0,+5], [0,+20] 거래일이다.
  - 주 판정 기간은 [0,+1]이고, 주 임계값은 0.01이다.
  - 민감도는 0.005, 0.01, 0.02로 본다.
- 최소 표본은 30이다. 이보다 적으면 "표본 부족"으로 표시한다.
- 정정공시는 분류하지도 백테스트하지도 않는다. 표시만 한다. `기타`는 백테스트 집계에서 제외한다.
- 결과는 `origin`(`live` / `backfill`)과 `classifier_version`별로 분리해서 집계한다.
- LLM 입력에서 회사명, 종목코드, 날짜를 가린다. live와 backfill에 동일하게 적용한다.
- 모델 이름은 별칭(`-latest`)이 아닌 고정 이름으로 설정한다.
- 실행 시각은 매일 KST 07:00이다(cron `0 22 * * *` UTC).
- 커버리지 목표: `pytest --cov=dartbot --cov-fail-under=80`
- 사이트는 `site/` 디렉터리에서 생성하고 Pages Actions로 배포한다. `docs/`는 설계 문서용이라 배포하지 않는다.

## Review Focus

1. **무상증자·액면분할 권리락으로 종가가 크게 뛰는 경우.** 원 종가로 수익률을 계산하면 −50% 같은 가짜 CAR이 나온다. 그래서 일별 수익률은 KRX 등락률(`FLUC_RT`)로 계산한다. 이 값은 기준가가 조정된 값이다. → Task 8 `test_ret_uses_fluc_rt_not_close_diff`
2. **거래정지, 상장폐지, 신규상장으로 기간 중 시세가 없는 종목.** 0% 수익률로 채우지 말고 `status="no_price"`로 집계에서 빼야 한다. → Task 9 `test_no_price_when_halted`
3. **배치 응답 일부가 잘못된 경우.** Gemini가 enum 밖 값을 주거나, 항목을 빠뜨리거나, JSON이 깨질 수 있다. 실행 전체가 죽지 않고, 실패 건만 단건으로 다시 시도한 뒤 그래도 실패하면 대기열에 남아야 한다. → Task 6 재시도 테스트 3개
4. **공시가 없는 날과 페이지 경계.** 공휴일이나 주말에는 공시가 없을 수 있는데(DART status `013`), 이것은 오류가 아니라 빈 목록이다. 결과가 100건을 넘으면 마지막 페이지까지 받아야 한다. → Task 3 `test_list_status_013_returns_empty`, `test_list_paginates_until_total_page`
5. **같은 날을 두 번 수집하거나 재실행하는 경우.** `rcept_no` 기준으로 중복이 생기지 않아야 한다. 주말이나 휴일 접수 공시는 다음 거래일이 t0이 된다. → Task 12 `test_rerun_same_day_no_duplicates`, Task 9 `test_t0_weekend_rolls_to_next_trading_day`

---

## 파일 구조

```
pyproject.toml / .gitignore / .env.example / README.md
src/dartbot/
  __init__.py
  __main__.py          CLI (argparse 서브커맨드)
  config.py            모든 설정값과 상수
  models.py            Disclosure, Classification, EventResult 데이터클래스
  storage.py           월별 JSONL, 상태 파일, 중복 제거
  dart_client.py       OpenDART list.json, document.xml
  filters.py           시장 필터, 제목 키워드 → 후보 유형, 정정 판정
  masking.py           LLM 입력 마스킹
  llm/
    base.py            Classifier 프로토콜, 입출력 dataclass, QuotaExceeded
    prompt.py          프롬프트 생성, PROMPT_VERSION
    gemini.py          GeminiClassifier
  classify_runner.py   대기열 선택, 하루 상한, 결과 저장
  krx_client.py        KRX Open API (krx-daily-report에서 이식)
  prices.py            일별 시세 캐시, 거래일 달력, 수익률 조회
  backtest.py          t0, CAR, 적중 판정
  stats.py             집계, t검정, 혼동행렬, 민감도
  site/
    build.py           JSON과 HTML 생성
    templates/         base.html, index.html, validation.html, ops.html
  pipeline.py          단계별 오케스트레이션
tests/                 모듈별 test_*.py, fixtures/
.github/workflows/     ci.yml, daily.yml, backfill.yml
data/                  커밋 대상
site/                  생성물. .gitignore에 넣고 Pages 아티팩트로만 배포
```

데이터 경로:
- `data/disclosures/YYYY/YYYY-MM.jsonl`
- `data/classifications/YYYY/YYYY-MM.jsonl`
- `data/prices/stocks/YYYY/YYYYMMDD.csv.gz`: 그날 STK와 KSQ 전 종목
- `data/prices/index/YYYY/YYYYMMDD.csv.gz`
- `data/results/events.jsonl`, `data/results/summary.json`
- `data/ops_log.jsonl`, `data/state.json`

---

### Task 1: 프로젝트 뼈대, 설정, 모델, CI

**Files:**
- Create:
  - `pyproject.toml`, `.gitignore`, `.env.example`
  - `src/dartbot/__init__.py`, `src/dartbot/config.py`, `src/dartbot/models.py`
  - `.github/workflows/ci.yml`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `config`의 상수
    - `TYPES: tuple[str, ...]`: 11개, Global Constraints 순서 그대로
    - `SENTIMENTS = ("긍정", "부정", "중립")`
    - `MARKETS = ("Y", "K")`, `PBLNTF_TYPES = ("B", "I")`
    - `CAR_WINDOWS = (1, 5, 20)`, `PRIMARY_WINDOW = 1`, `PRIMARY_THRESHOLD = 0.01`, `THRESHOLDS = (0.005, 0.01, 0.02)`, `MIN_SAMPLE = 30`
    - `GEMINI_MODEL: str`, `BATCH_SIZE = 10`, `REQUESTS_PER_MINUTE = 10`, `DAILY_REQUEST_CAP = 200`
    - `BODY_MAX_CHARS = 4000`
    - `LIVE_START_DATE: str`: YYYYMMDD. Task 13에서 확정할 때까지 `"99991231"`로 둔다.
    - `BACKFILL_START = "20251124"`
    - `DATA_DIR = Path("data")`, `SITE_DIR = Path("site")`
  - `models.py`의 frozen dataclass 세 개. 각각 `to_dict() -> dict`와 `classmethod from_dict(d: dict)`를 가진다.
    - `Disclosure(rcept_no: str, rcept_dt: str, corp_code: str, corp_name: str, stock_code: str, corp_cls: str, report_nm: str, is_correction: bool, candidate_type: str | None)`
    - `Classification(rcept_no: str, summary: tuple[str, str, str], type: str, sentiment: str, confidence: float, rationale: str, classifier_version: str, origin: str, input_mode: str, classified_at: str)`
      - `origin`은 `"live"` 또는 `"backfill"`
      - `input_mode`는 `"body"` 또는 `"title_only"`
    - `EventResult(rcept_no: str, t0: str | None, car: dict[int, float | None], status: str, source: str)`
      - `status`는 `"ok"`, `"pending"`, `"no_price"` 중 하나

- [ ] **Step 1: 테스트 작성.** `tests/test_models.py`
  - `test_disclosure_roundtrip`: `Disclosure.from_dict(d.to_dict()) == d`
  - `test_classification_rejects_unknown_type`: `type="배당"`이면 `ValueError`
  - `test_classification_rejects_bad_sentiment`
  - `test_classification_rejects_confidence_out_of_range`: 1.5이면 `ValueError`
  - `test_event_result_car_keys_roundtrip_as_int`: JSON을 거치면 키가 str이 된다. `from_dict` 후에는 int여야 한다.
  - 검증은 `__post_init__`에서 한다.
- [ ] **Step 2: 실패 확인.** `pytest tests/test_models.py -v` → `ModuleNotFoundError: dartbot`
- [ ] **Step 3: 구현.**
  - `pyproject.toml`은 krx-daily-report 형식을 따른다. setuptools, `src` 레이아웃, `[dev]` extras, `pythonpath=["src"]`
  - 의존성: `requests>=2.31, pandas>=2.1, numpy>=1.26, scipy>=1.11, python-dotenv>=1.0, tzdata>=2024.1, google-genai>=1.0, jinja2>=3.1`
  - `.gitignore`: `.env`, `site/`, `__pycache__/`, `.coverage`, `*.egg-info/`
  - `.env.example`: 세 키를 `여기에_발급받은_키` 형식으로 둔다.
  - `ci.yml`은 krx-daily-report의 `ci.yml`과 같고, `--cov=dartbot`만 바꾼다.
  - `GEMINI_MODEL`은 구현 시점에 무료로 쓸 수 있는 Flash 계열의 고정 이름으로 정한다. Task 6 Step 5에서 확인한다.
- [ ] **Step 4: 통과 확인.** `pytest tests/test_models.py -v` → 5 passed
- [ ] **Step 5: 커밋.**

```bash
git init -b main
git add -A
git commit -m "chore: project skeleton, config, models, CI"
```

### Task 2: 저장소 계층 (JSONL, 상태, 중복 제거)

**Files:**
- Create: `src/dartbot/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `models.*`
- Produces:
  - `append_disclosures(items: list[Disclosure], root: Path) -> int`
    - `rcept_dt` 기준 월별 파일에 추가하고, 새로 추가된 건수를 반환한다.
    - 이미 있는 `rcept_no`는 건너뛴다.
  - `load_disclosures(root: Path, start: str | None = None, end: str | None = None) -> list[Disclosure]`
  - `append_classifications(items: list[Classification], root: Path) -> int`
    - `(rcept_no, classifier_version)` 기준으로 중복을 건너뛴다.
    - 월은 해당 공시의 `rcept_no` 앞 8자리(접수일)로 정한다.
  - `load_classifications(root: Path) -> list[Classification]`
  - `read_state(root: Path) -> dict`: 파일이 없으면 `{"last_collected_date": None}`
  - `write_state(root: Path, state: dict) -> None`: 임시 파일에 쓴 뒤 `os.replace`로 교체한다.
  - `append_ops_log(root: Path, record: dict) -> None`, `load_ops_log(root: Path) -> list[dict]`
- 모든 JSONL은 `ensure_ascii=False`, UTF-8로 쓴다.

- [ ] **Step 1: 테스트 작성.** 모두 `tmp_path`를 쓴다.
  - `test_append_disclosures_dedupes_by_rcept_no`: 같은 2건을 두 번 넣으면 두 번째 반환값이 0이고, 로드 결과는 2건이다.
  - `test_disclosures_split_by_month`: 20251130 건과 20251201 건이 `2025/2025-11.jsonl`과 `2025/2025-12.jsonl`로 나뉜다.
  - `test_load_disclosures_date_filter`
  - `test_classification_dedupe_allows_new_version`: 같은 `rcept_no`라도 버전이 다르면 저장된다.
  - `test_state_missing_file_defaults`
  - `test_jsonl_is_utf8_readable`: 파일 원문에 `"유상증자"`가 그대로 보인다.
- [ ] **Step 2: 실패 확인.** `pytest tests/test_storage.py -v` → FAIL
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_storage.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: JSONL storage with dedupe and state file`

### Task 3: OpenDART 클라이언트

**Files:**
- Create: `src/dartbot/dart_client.py`
- Create: `tests/fixtures/dart_list_page1.json`, `dart_list_page2.json`, `dart_document.zip`
  - zip에는 HTML 태그가 섞인 작은 XML을 하나 넣는다.
  - cp949 테스트용 zip은 테스트 안에서 즉석으로 만든다.
- Test: `tests/test_dart_client.py`

**Interfaces:**
- Produces:
  - `class DartApiError(RuntimeError)`
  - `class DartClient(api_key: str | None = None, session: requests.Session | None = None)`
    - 키가 없으면 `DART_API_KEY` 환경변수를 읽고, 그것도 없으면 `DartApiError`
    - `list_disclosures(date: str, corp_cls: str, pblntf_ty: str) -> list[dict]`
      - `GET https://opendart.fss.or.kr/api/list.json`
      - 파라미터: `crtfc_key`, `bgn_de=end_de=date`, `corp_cls`, `pblntf_ty`, `page_count=100`, `page_no`를 1부터 응답의 `total_page`까지
    - `document_text(rcept_no: str, max_chars: int) -> str`
      - `GET https://opendart.fss.or.kr/api/document.xml?crtfc_key&rcept_no` 응답은 zip이다.
      - zip 안의 모든 파일을 읽는다. 인코딩은 utf-8로 먼저 시도하고, 실패하면 cp949로 읽는다.
      - 태그를 제거하고, 연속 공백을 하나로 줄이고, `max_chars`로 자른다.
      - 응답이 zip이 아니고 JSON 오류 본문이면 `DartApiError`
- 상태 코드
  - `"000"`: 정상
  - `"013"`: 빈 목록 반환
  - 그 외(`"010"`, `"011"`, `"020"` 등): `status`와 `message`를 담아 `DartApiError`
  - 네트워크 오류: krx-daily-report `_get_with_retry`와 같은 방식으로 3회 재시도하고, 시도할 때마다 `2 * attempt`초 대기한다.

- [ ] **Step 1: 테스트 작성.** `requests` 세션은 가짜 객체로 대체한다.
  - `test_list_paginates_until_total_page`: page1이 `total_page=2`이면 두 페이지를 합친 건수를 반환한다.
  - `test_list_status_013_returns_empty`
  - `test_list_status_020_raises`: 메시지에 `"020"`이 들어간다.
  - `test_document_text_strips_tags_and_truncates`
  - `test_document_text_cp949_fallback`
  - `test_document_error_json_raises`
  - `test_missing_key_raises`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_dart_client.py -v` → PASS
- [ ] **Step 5: 실제 API 확인 (수동, `.env`에 키 필요).**
  - `python -c "from dotenv import load_dotenv; load_dotenv(); from dartbot.dart_client import DartClient; c=DartClient(); r=c.list_disclosures('20261120','Y','B'); print(len(r), [x['report_nm'] for x in r[:5]])"`
  - 기대 결과: 건수와 제목 5개가 출력된다.
  - 그 결과 중 1건의 `rcept_no`로 `document_text`를 호출해서 앞 300자가 읽을 만한 텍스트인지 본다.
- [ ] **Step 6: 커밋.** `feat: OpenDART list and document client`

### Task 4: 필터 (시장, 후보 유형, 정정)

**Files:**
- Create: `src/dartbot/filters.py`
- Modify: `src/dartbot/config.py`. `TITLE_RULES`, `CORRECTION_PREFIXES`를 추가한다.
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `models.Disclosure`, `config.MARKETS`
- Produces:
  - `normalize_title(report_nm: str) -> str`
    - 공백을 제거하고 `ㆍ`과 `·`를 `·`로 통일한다.
    - 앞쪽 대괄호 접두사(`[기재정정]` 등)를 제거한다.
  - `is_correction(report_nm: str) -> bool`: 원 제목이 `CORRECTION_PREFIXES` 중 하나로 시작하는지 본다.
  - `candidate_type(report_nm: str) -> str | None`
    - `TITLE_RULES`를 위에서부터 차례로 보고, 정규화한 제목에 키워드가 처음으로 포함되는 규칙의 유형을 반환한다.
  - `to_disclosure(row: dict) -> Disclosure | None`
    - `corp_cls`가 `MARKETS`에 없거나 `stock_code`가 비어 있으면 None
    - 그 외에는 `candidate_type`이 None이어도 `Disclosure`를 반환한다. 운영 현황에서 제외 건수와 제외된 제목을 보여주기 위해서다.
- config 값
  - `CORRECTION_PREFIXES = ("[기재정정]", "[첨부정정]", "[첨부추가]", "[변경등록]", "[연장결정]")`
  - `TITLE_RULES: tuple[tuple[str, str], ...]`. (키워드, 유형) 쌍이고 순서가 의미를 가진다.
    1. `유무상증자결정` → `유상증자`. `무상증자결정`보다 먼저 검사해야 한다.
    2. `무상증자결정` → `무상증자`
    3. `유상증자결정` → `유상증자`
    4. `주식소각결정` → `자기주식 소각`
    5. `자기주식취득신탁계약체결결정` → `자기주식 취득`
    6. `자기주식취득결정` → `자기주식 취득`
    7. `자기주식처분결정` → `자기주식 처분`
    8. `단일판매·공급계약체결` → `단일판매·공급계약`
    9. `최대주주변경` → `최대주주 변경`
    10. `전환사채권발행결정` → `전환사채·신주인수권부사채 발행`
    11. `신주인수권부사채권발행결정` → `전환사채·신주인수권부사채 발행`
    12. `회사분할합병결정` → `합병·분할`
    13. `회사합병결정` → `합병·분할`
    14. `회사분할결정` → `합병·분할`
    15. `영업(잠정)실적` → `영업(잠정)실적`
    16. `매출액또는손익구조` → `영업(잠정)실적`

- [ ] **Step 1: 테스트 작성.** `test_candidate_type`을 parametrize로 만든다.
  - `"주요사항보고서(유상증자결정)"` → `유상증자`
  - `"주요사항보고서(무상증자결정)"` → `무상증자`
  - `"주요사항보고서(유무상증자결정)"` → `유상증자`
  - `"단일판매ㆍ공급계약체결"` → `단일판매·공급계약`
  - `"[기재정정]주요사항보고서(자기주식취득결정)"` → `자기주식 취득`
  - `"최대주주변경을수반하는주식양수도계약체결"` → `최대주주 변경`
  - `"영업(잠정)실적(공정공시)"` → `영업(잠정)실적`
  - `"임원ㆍ주요주주특정증권등소유상황보고서"` → None
  - 그 밖의 테스트
    - `test_is_correction`: 위 기재정정 제목은 True, 원 제목은 False
    - `test_to_disclosure_drops_konex_and_unlisted`: `corp_cls="N"` → None, `stock_code=""` → None
    - `test_to_disclosure_keeps_non_candidate`: 후보가 아닌 제목은 `candidate_type=None`인 Disclosure
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_filters.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: market filter, title keyword typing, correction flag`

### Task 5: LLM 입력 마스킹

**Files:**
- Create: `src/dartbot/masking.py`
- Test: `tests/test_masking.py`

**Interfaces:**
- Produces: `mask_text(text: str, corp_name: str, stock_code: str) -> str`
  - 회사명을 `"A사"`로 바꾼다.
    - 원래 이름과 `(주)`, `㈜`, `주식회사`가 앞이나 뒤에 붙은 변형을 모두 바꾼다.
    - 긴 변형부터 치환한다.
  - 그 회사의 6자리 `stock_code`와, 앞뒤가 숫자가 아닌 6자리 숫자를 `"[코드]"`로 바꾼다.
  - 날짜 표현(`2026-11-20`, `2026.11.20`, `2026/11/20`, `2026년 11월 20일`, `20261120`)을 `"[날짜]"`로 바꾼다. 날짜 패턴을 코드 패턴보다 먼저 적용한다.
  - 금액과 비율 숫자는 그대로 둔다.

- [ ] **Step 1: 테스트 작성.**
  - `test_masks_company_variants`: `"(주)에코프로비엠"`, `"에코프로비엠(주)"`, `"주식회사 에코프로비엠"`, `"㈜에코프로비엠"`이 모두 `"A사"`가 된다.
  - `test_masks_dates_all_formats`
  - `test_keeps_amounts_and_ratios`: `"1,234억원"`, `"15.3%"`, `"1,000,000주"`는 그대로 남는다.
  - `test_masks_stock_code`: `"247540"` → `"[코드]"`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_masking.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: mask company, code, and dates in LLM input`

### Task 6: 분류기 인터페이스, 프롬프트, Gemini 구현

**Files:**
- Create: `src/dartbot/llm/__init__.py`, `llm/base.py`, `llm/prompt.py`, `llm/gemini.py`
- Test: `tests/test_prompt.py`, `tests/test_gemini.py`

**Interfaces:**
- Consumes: `config.TYPES`, `SENTIMENTS`, `GEMINI_MODEL`, `REQUESTS_PER_MINUTE`
- Produces:
  - `llm.base`
    - `class QuotaExceeded(RuntimeError)`
    - `ClassifierInput(rcept_no: str, title: str, body: str)`: frozen dataclass. title과 body는 이미 마스킹된 값이다.
    - `ClassifierOutput(rcept_no: str, summary: tuple[str, str, str], type: str, sentiment: str, confidence: float, rationale: str)`: frozen dataclass
    - `class Classifier(Protocol)`
      - `version: str`
      - `classify_batch(items: list[ClassifierInput]) -> tuple[list[ClassifierOutput], list[str]]`
      - 반환값은 (성공 목록, 실패한 rcept_no 목록)이다.
  - `llm.prompt`
    - `PROMPT_VERSION = "p1"`
    - `build_prompt(items: list[ClassifierInput]) -> str`
    - 프롬프트에 반드시 들어갈 내용
      1. 역할: 한국 주식시장 공시 분석가
      2. 유형 enum 11개와 각 유형의 한 줄 정의
      3. 영향 정의: "기존 주주 입장에서 공시 직후 1~2거래일 주가에 미칠 방향"
      4. 요약은 한국어 정확히 3문장. 회사명은 "A사"로 유지한다.
      5. 각 항목의 `rcept_no`를 그대로 되돌릴 것
      6. 입력에 없는 정보를 추측하지 말 것
  - `llm.gemini.GeminiClassifier(api_key: str | None = None, model: str = config.GEMINI_MODEL, client=None, sleep: Callable[[float], None] = time.sleep)`
    - `version = f"{model}+{PROMPT_VERSION}"`
    - `client`가 None이면 `google.genai.Client(api_key=키 또는 GEMINI_API_KEY 환경변수)`를 만든다.
    - 호출: `client.models.generate_content(model=..., contents=prompt, config={"response_mime_type": "application/json", "response_schema": <항목 배열 스키마. type과 sentiment는 enum으로 제한>, "temperature": 0})`
    - 매 호출 전에 직전 호출과의 간격을 `60 / REQUESTS_PER_MINUTE`초 이상 둔다. 부족하면 주입한 `sleep`을 쓴다.
    - 오류 메시지나 상태에 429 / `RESOURCE_EXHAUSTED`가 있으면 `QuotaExceeded`
    - 응답 검증: enum 밖 값, `summary`가 3개가 아님, `confidence`가 [0,1] 밖, 응답에 없는 `rcept_no`는 모두 실패로 본다.
    - 실패 건은 단건 배치로 1회 다시 시도한다. 그래도 실패하면 실패 목록에 넣는다.
    - JSON 파싱이 실패하면 배치 전체를 실패로 보고 단건씩 다시 시도한다.

- [ ] **Step 1: 테스트 작성.**
  - `test_prompt.py`
    - `test_prompt_lists_all_types_and_rcept_nos`
    - `test_prompt_contains_no_unmasked_placeholder_leak`: 입력에 넣은 `"A사"`가 그대로 있다.
  - `test_gemini.py`: 가짜 `client`를 쓴다. `client.models.generate_content`가 미리 정한 `.text`를 돌려주고, 호출 기록을 남긴다.
    - `test_batch_success_maps_by_rcept_no`: 순서가 섞인 응답도 `rcept_no`로 매핑된다.
    - `test_invalid_enum_retried_singly_then_failed`: 3건 중 1건이 `type="배당"` → 단건 재시도도 잘못된 응답 → 성공 2, 실패 1, 총 호출 2회
    - `test_missing_item_retried_singly_and_recovered`
    - `test_malformed_json_retries_all_singly`: 3건 배치에서 JSON이 깨짐 → 단건 3회 → 모두 성공
    - `test_quota_error_raises_quota_exceeded`
    - `test_rate_limit_sleeps_between_calls`: 가짜 시계와 가짜 sleep으로, 두 번째 호출 전에 `sleep(6.0)`이 불렸는지 본다(RPM 10).
    - `test_version_string`: `"<model>+p1"`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_prompt.py tests/test_gemini.py -v` → PASS
- [ ] **Step 5: 실제 API 확인 (수동, 키 필요).**
  - Task 3에서 받은 실제 공시 3건을 마스킹해서 `classify_batch`를 1회 호출하고 결과를 출력한다.
  - 기대 결과: 3건 모두 성공하고, 요약이 읽을 만하다.
  - Google AI Studio에서 현재 모델의 무료 한도(RPM, RPD)를 확인한다.
    - `REQUESTS_PER_MINUTE`는 한도의 80% 이하로 맞춘다.
    - `DAILY_REQUEST_CAP`은 RPD의 80% 이하로 맞춘다.
    - `GEMINI_MODEL`을 확정한다.
- [ ] **Step 6: 커밋.** `feat: Gemini batch classifier with schema validation and retries`

### Task 7: 분류 대기열 실행기

**Files:**
- Create: `src/dartbot/classify_runner.py`
- Test: `tests/test_classify_runner.py`

**Interfaces:**
- Consumes:
  - `storage.load_disclosures`, `load_classifications`, `append_classifications`
  - `DartClient.document_text`
  - `masking.mask_text`
  - `llm.base.*`
- Produces:
  - `origin_of(d: Disclosure) -> str`: `"live"` if `d.rcept_dt >= config.LIVE_START_DATE` else `"backfill"`
  - `pending_queue(disclosures: list[Disclosure], classifications: list[Classification], version: str) -> list[Disclosure]`
    - 대상: `candidate_type`이 있고, `is_correction`이 False이고, 해당 `version`의 분류가 없는 공시
    - 정렬: live를 먼저 `rcept_dt` 내림차순으로, 그다음 backfill을 `rcept_dt` 내림차순으로
  - `run_classification(root: Path, dart: DartClient, classifier: Classifier, max_requests: int, now: Callable[[], datetime]) -> dict`
    - 반환값: `{"classified": int, "failed": int, "remaining": int, "stopped_by_quota": bool}`
    - 대기열을 `BATCH_SIZE`씩 묶고, 배치마다 다음을 한다.
      1. 각 공시의 본문을 `document_text(rcept_no, BODY_MAX_CHARS)`로 가져온다. `DartApiError`가 나면 `body=""`로 두고 `input_mode="title_only"`
      2. 제목과 본문을 `mask_text`로 가린다.
      3. `classify_batch`를 호출한다.
      4. 결과를 `Classification`으로 바꿔 바로 저장한다. `origin`, `input_mode`, `classified_at`(KST ISO)을 채운다.
    - 배치 하나가 요청 하나로 계산된다. 단건 재시도분은 분류기 내부에서 처리하므로 여기서는 세지 않는다. 보수적으로 잡으려고 `DAILY_REQUEST_CAP`을 낮게 둔 것이다.
    - `QuotaExceeded`가 나면 그 배치는 저장하지 않고 멈추고 `stopped_by_quota=True`

- [ ] **Step 1: 테스트 작성.** 가짜 DartClient와 가짜 Classifier를 쓴다.
  - `test_queue_live_before_backfill_newest_first`
  - `test_queue_skips_corrections_and_non_candidates`
  - `test_queue_skips_already_classified_same_version`
  - `test_body_failure_falls_back_to_title_only`
  - `test_max_requests_caps_batches`: `max_requests=2`, `BATCH_SIZE=10`, 대기 25건 → `classified == 20`, `remaining == 5`
  - `test_quota_stops_and_keeps_progress`: 두 번째 배치에서 `QuotaExceeded` → 첫 배치 10건만 저장되고 `stopped_by_quota is True`
  - `test_failed_items_stay_in_queue`: 분류기가 실패로 돌려준 건은 저장되지 않아서 다음 실행에 다시 대기열에 나온다.
  - `test_masking_applied_before_classify`: 가짜 Classifier가 받은 입력에 원래 회사명이 없다.
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_classify_runner.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: classification queue with daily cap and live-first priority`

### Task 8: KRX 시세 클라이언트와 가격 캐시

**Files:**
- Create: `src/dartbot/krx_client.py`
  - krx-daily-report의 `src/krxreport/krx_client.py`를 이식한다.
  - `BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"`, 헤더 `AUTH_KEY`, 응답 키 `OutBlock_1`을 그대로 쓴다.
- Create: `src/dartbot/prices.py`
- Modify: `src/dartbot/config.py`. `KRX_ENDPOINTS`, `KRX_STOCK_FIELDS`, `KRX_INDEX_FIELDS`, `KRX_INDEX_NAMES`를 추가한다.
- Test: `tests/test_krx_client.py`, `tests/test_prices.py`

**Interfaces:**
- Produces:
  - `krx_client.KrxApiError`
  - `krx_client.KrxClient(api_key=None, session=None)`
    - `fetch(kind: str, date: str) -> list[dict]`
    - 401/403이 나면 `KrxApiError`. 메시지에 "KRX Open API에서 해당 서비스 이용 신청 여부를 확인하세요"를 넣는다.
  - `config.KRX_ENDPOINTS`: 이름은 Step 5 probe로 확정한다.
    - `stk`: `sto/stk_bydd_trd`
    - `ksq`: `sto/ksq_bydd_trd`
    - `kospi_idx`: `idx/kospi_dd_trd`
    - `kosdaq_idx`: `idx/kosdaq_dd_trd`
  - `config.KRX_INDEX_NAMES = {"kospi_idx": ("코스피", "KOSPI"), "kosdaq_idx": ("코스닥", "KOSDAQ")}`
    - 응답의 지수명이 첫 값과 같은 행만 남기고, 두 번째 값으로 저장한다.
  - `prices.download_day(client: KrxClient, date: str, root: Path) -> bool`
    - 종목 파일 하나와 지수 파일 하나를 저장한다.
    - 네 응답이 모두 비어 있으면 휴장일이다. False를 반환하고 아무것도 쓰지 않는다.
    - 두 파일이 이미 있으면 호출 없이 True를 반환한다.
    - 종목 파일 컬럼: `date, code, name, market, close, ret`
      - `market`은 `"Y"` 또는 `"K"`
      - `ret = float(FLUC_RT) / 100`
      - `code`는 6자리 단축코드다.
    - 지수 파일 컬럼: `date, index, close, ret`
  - `prices.download_range(client: KrxClient, start: str, end: str, root: Path) -> int`: 달력의 날짜를 순회하고, 새로 저장한 거래일 수를 반환한다.
  - `prices.trading_days(root: Path) -> list[str]`: 저장된 종목 파일 기준, 오름차순
  - `prices.stock_returns(root: Path, code: str, days: list[str]) -> list[float | None]`
  - `prices.market_returns(root: Path, market: str, days: list[str]) -> list[float | None]`: `"Y"`는 KOSPI, `"K"`는 KOSDAQ
  - 날짜별 파일은 `functools.lru_cache`로 한 번만 읽는다. 캐시 키는 `(root, date)`

- [ ] **Step 1: 테스트 작성.**
  - `test_krx_client.py`
    - `test_fetch_uses_auth_header_and_basDd`
    - `test_401_raises_with_service_hint`
    - `test_retries_then_raises`
  - `test_prices.py`
    - `test_download_day_holiday_writes_nothing`
    - `test_download_day_skips_existing_files`: 가짜 클라이언트가 호출되지 않는다.
    - `test_ret_uses_fluc_rt_not_close_diff` (Review Focus 1)
      - 픽스처: 전일 종가 10,000, 당일 종가 5,000, `FLUC_RT="2.00"`(무상증자 권리락)
      - 결과: `ret == approx(0.02)`
    - `test_index_rows_filtered_to_kospi_kosdaq`
    - `test_stock_returns_missing_code_gives_none`
    - `test_trading_days_sorted`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_krx_client.py tests/test_prices.py -v` → PASS
- [ ] **Step 5: 실제 API 확인 (수동, KRX 서비스 추가 신청 후).**
  - `python -c`로 네 kind를 `20261120`에 각각 호출하고, 첫 행의 키 목록과 행 수를 출력한다.
  - 필드 이름을 확인해서 `KRX_STOCK_FIELDS`와 `KRX_INDEX_FIELDS`에 반영한다. 확인할 이름의 예: 단축코드(`ISU_SRT_CD` 또는 `ISU_CD`), `FLUC_RT`, `IDX_NM`, `CLSPRC_IDX`
  - 확인용 숫자: 유가증권 약 950개 행, 코스닥 약 1,700개 행
  - 401/403이 나면 멈추고 사용자에게 서비스 신청 상태를 확인해 달라고 한다.
  - KRX에서 데이터를 받을 수 없으면 스펙 6절의 yfinance 대체로 전환한다. 이 Task의 계획을 다시 써서 사용자 확인을 받는다.
- [ ] **Step 6: 커밋.** `feat: KRX stock/index daily prices with adjusted returns`

### Task 9: 백테스트 (t0, CAR, 적중)

**Files:**
- Create: `src/dartbot/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes:
  - `prices.trading_days`, `stock_returns`, `market_returns`
  - `storage.load_disclosures`, `load_classifications`
  - `models.EventResult`
- Produces:
  - `event_t0(rcept_dt: str, days: list[str]) -> str | None`: `rcept_dt` 이상인 첫 거래일. 없으면 None
  - `compute_event(d: Disclosure, root: Path, days: list[str]) -> EventResult`
    - `CAR[k] = Σ (r_i − r_m,i)`. i는 t0부터 t0+k 거래일까지 포함한다(k+1일).
    - 기간 끝 거래일이 아직 데이터에 없으면 그 k는 None이다.
    - t0이 None이거나 `CAR[PRIMARY_WINDOW]`가 기간 미도래로 None이면 `status="pending"`
    - 기간 안에 종목이나 지수 수익률이 하나라도 None이면 그 k는 None이다. `CAR[PRIMARY_WINDOW]`가 이 이유로 None이면 `status="no_price"`
    - 그 외에는 `status="ok"`, `source="krx"`
  - `judge(sentiment: str, car: float, threshold: float) -> bool`
    - 긍정: `car > threshold`
    - 부정: `car < -threshold`
    - 중립: `abs(car) <= threshold`
  - `actual_label(car: float, threshold: float) -> str`: 위 판정과 대응하는 실제 레이블
  - `run_backtest(root: Path) -> list[EventResult]`
    - 분류가 하나 이상 있는 비정정 공시 중 최신 분류의 `type != "기타"`인 것을 대상으로 한다.
    - 전부 다시 계산해서 `data/results/events.jsonl`을 덮어쓴다. 이벤트는 공시 단위라서 분류기 버전과 무관하다.

- [ ] **Step 1: 테스트 작성.** 픽스처 헬퍼로 3종목 × 25거래일 가격 디렉터리를 `tmp_path`에 만든다.
  - `test_t0_weekend_rolls_to_next_trading_day` (Review Focus 5): 토요일 접수 → 다음 월요일
  - `test_car_window_sums_excess_returns`
    - 종목 수익률 [0.03, 0.01], 시장 [0.01, 0.00]
    - `CAR[1] == approx(0.03)`
  - `test_pending_when_window_not_elapsed`: 마지막 거래일에 접수된 공시
  - `test_no_price_when_halted` (Review Focus 2): t0+1에 종목 행이 없으면 `status == "no_price"`이고 `car[1] is None`
  - `test_long_window_none_but_primary_ok`: `CAR[20]`은 None이어도 `CAR[1]`이 있으면 `status == "ok"`
  - `test_judge`를 parametrize로 만든다.
    - (긍정, 0.011, 0.01) → True
    - (긍정, 0.01, 0.01) → False
    - (중립, -0.01, 0.01) → True
    - (부정, -0.02, 0.01) → True
    - (부정, 0.0, 0.01) → False
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_backtest.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: market-adjusted CAR event study and hit judgment`

### Task 10: 통계 집계

**Files:**
- Create: `src/dartbot/stats.py`
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: `list[Classification]`, `list[EventResult]`, `backtest.judge`, `backtest.actual_label`
- Produces: `summarize(classifications: list[Classification], events: list[EventResult], now: str) -> dict`
  - 호출한 쪽이 결과를 `data/results/summary.json`에 쓴다.
  - 분류와 이벤트는 `rcept_no`로 조인한다.
  - 그룹 키는 `(origin, classifier_version)`이다.

```
{"generated_at": str,
 "groups": [{"origin": str, "classifier_version": str,
   "n_classified": int, "n_ok": int, "n_pending": int, "n_no_price": int,
   "by_sentiment": {"긍정": {"1": {"mean": float, "n": int, "p_value": float|None, "insufficient": bool}, "5": {...}, "20": {...}}, ...},
   "by_type": {type: {"n": int, "mean_car1": float, "hit_rate": float, "insufficient": bool}},
   "confusion": {pred: {actual: int}},
   "directional_hit_rate": float|None,
   "hit_rate_by_threshold": {"0.005": float, "0.01": float, "0.02": float},
   "hit_rate_by_confidence": {"0.0-0.5": float|None, "0.5-0.7": ..., "0.7-0.9": ..., "0.9-1.0": ...}}]}
```

- 세부 규칙
  - 평균, 적중률, 혼동행렬은 `status == "ok"` 이벤트만으로 계산한다.
  - 기간별 평균은 그 기간 CAR이 None이 아닌 것만 쓴다.
  - `p_value`: `scipy.stats.ttest_1samp(cars, 0).pvalue`. n < 2이면 None
  - `insufficient`: `n < MIN_SAMPLE`
  - `directional_hit_rate`: 예측이 중립이 아닌 건 중 `sign(CAR[1])`이 예측 방향과 같은 비율. 대상이 없으면 None
  - 확신도 구간은 아래쪽 경계를 포함하고, 마지막 구간은 1.0을 포함한다. 비어 있으면 None

- [ ] **Step 1: 테스트 작성.**
  - `test_groups_split_by_origin_and_version`
  - `test_insufficient_flag_below_30`: 29건이면 True, 30건이면 False
  - `test_confusion_counts`
  - `test_directional_hit_excludes_neutral_predictions`
  - `test_pvalue_none_for_single_sample`
  - `test_excludes_pending_and_no_price`
  - `test_confidence_buckets_edges`: 0.5는 `"0.5-0.7"`, 1.0은 `"0.9-1.0"`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_stats.py -v` → PASS
- [ ] **Step 5: 커밋.** `feat: validation statistics by origin and classifier version`

### Task 11: 정적 사이트 생성

**Files:**
- Create: `src/dartbot/site/__init__.py`, `site/build.py`
- Create: `site/templates/base.html`, `index.html`, `validation.html`, `ops.html`
- Modify: `pyproject.toml`. 템플릿을 패키지 데이터에 넣는다: `[tool.setuptools.package-data] dartbot = ["site/templates/*.html"]`
- Test: `tests/test_site.py`

**Interfaces:**
- Consumes:
  - storage 로더들, `load_ops_log`, `read_state`
  - `data/results/summary.json`, `events.jsonl`
- Produces: `build_site(data_root: Path, out: Path) -> None`. 다음 파일을 만든다.
  - `out/data/days/YYYYMMDD.json`: 그날 공시 목록
    - 필드: 회사명, 시장, 제목, DART 링크 `https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`, 유형, 영향, 요약 3줄, 확신도, 정정 여부, CAR(있으면)
    - 분류는 최신 버전을 쓴다.
  - `out/data/days/index.json`: 날짜 목록
  - `out/data/summary.json`: 집계 결과 복사본
  - `out/data/ops.json`
    - 마지막 실행 시각
    - 누적 수집·후보·분류·실패 건수, 남은 대기열
    - 일별 처리량
    - 키워드 필터에서 제외된 최근 제목 50개(키워드 보완용)
  - `out/index.html`: 오늘의 공시
    - 날짜 선택(기본값은 최신 날짜)과 유형 필터가 있다.
    - 영향 배지는 긍정 초록, 부정 빨강, 중립 회색이고 글자도 함께 표시한다.
  - `out/validation.html`: 검증 결과
    - live/backfill 토글과 버전 선택(기본은 표본이 가장 많은 최신 버전)
    - 영향별 평균 CAR 막대그래프(기간 3개), 유형별 표, 혼동행렬, 민감도 표
    - `insufficient`이면 "표본 부족" 배지
    - backfill을 선택하면 미래 정보 혼입 가능성과 마스킹 완화 안내문을 상단에 고정으로 표시한다.
  - `out/ops.html`: 운영 현황 (`ops.json` 기반, 일별 처리량 선그래프)
- 공통 규칙
  - 차트는 `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`
  - 서버에서 렌더링하는 부분은 Jinja2 `autoescape=True`로 출력한다.
  - JS로 넣는 공시 제목과 요약은 `textContent`만 쓴다. `innerHTML`은 쓰지 않는다.
  - 상단 내비게이션으로 세 페이지를 오간다. 375px 너비에서도 가로 스크롤이 생기지 않게 만든다.
  - 푸터에 "이 사이트는 투자 조언이 아닙니다" 문구를 넣는다.

- [ ] **Step 1: 테스트 작성.** 작은 픽스처 데이터 디렉터리를 쓴다.
  - `test_build_creates_all_pages_and_json`
  - `test_day_json_contains_dart_link`
  - `test_no_innerhtml_in_templates`: 템플릿 문자열에 `innerHTML`이 없다.
  - `test_backfill_warning_text_present`
  - `test_latest_version_used_for_day_json`: 같은 공시에 분류가 두 버전 있으면 최신 `classified_at`의 결과를 쓴다.
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_site.py -v` → PASS
- [ ] **Step 5: 눈으로 확인.**
  - 픽스처로 사이트를 만든 뒤 `python -m http.server -d site 8000`을 띄운다.
  - 브라우저로 세 페이지를 데스크톱과 375px 너비에서 모두 확인한다.
  - 콘솔 오류가 없어야 한다.
- [ ] **Step 6: 커밋.** `feat: static dashboard (disclosures, validation, ops)`

### Task 12: 파이프라인, CLI, 워크플로

**Files:**
- Create: `src/dartbot/pipeline.py`, `src/dartbot/__main__.py`
- Create: `.github/workflows/daily.yml`, `.github/workflows/backfill.yml`
- Test: `tests/test_pipeline_cli.py`

**Interfaces:**
- Consumes: 모든 이전 Task
- Produces:
  - `pipeline.collect(root: Path, dart: DartClient, start: str, end: str, move_state: bool) -> dict`
    - 날짜마다 `MARKETS` × `PBLNTF_TYPES`를 조회하고, `to_disclosure`로 변환해서 `append_disclosures`로 저장한다.
    - 날짜별로 `{date, fetched, listed, candidates, new}`를 `append_ops_log`에 남긴다.
    - `move_state=True`이고 `end`가 `last_collected_date`보다 뒤이면 상태를 갱신한다.
    - 반환값은 합계다.
  - `pipeline.daily(root: Path, today: date, dart, krx, classifier) -> dict`
    1. `end = today − 1일`
    2. `start = last_collected_date + 1일`. 상태가 없으면 `end` 하루만 수집한다.
    3. `start > end`이면 수집을 건너뛴다.
    4. `collect(move_state=True)`
    5. 가격: `download_range(krx, start − 40일, end)`
    6. `run_classification(max_requests=DAILY_REQUEST_CAP)`
    7. `run_backtest`
    8. `summarize` 결과를 `summary.json`에 쓴다.
    9. 실행 요약을 `ops_log`에 남긴다.
    10. `build_site(root, SITE_DIR)`
  - `pipeline.backfill(root, start, end, dart, krx) -> dict`
    - `collect(move_state=False)`와 `download_range(start − 40일, end)`만 한다. 분류는 daily가 대기열로 처리한다.
  - CLI 서브커맨드 (`python -m dartbot ...`)
    - `daily [--date YYYYMMDD]`: `--date`가 있으면 그날을 today로 본다.
    - `backfill --start --end`
    - `classify [--max-requests N]`
    - `backtest`, `site`
    - `probe dart|krx|gemini [--date]`: Task 3·6·8의 수동 확인을 명령 하나로 할 수 있게 한다.
  - 시작할 때 `load_dotenv()`를 호출한다.
  - 필수 키가 없으면 어떤 키가 없는지 한국어로 출력하고 종료 코드 2로 끝난다.
  - `GITHUB_OUTPUT` 환경변수가 있으면 `status=ok`, `date=<end>`를 기록한다(krx-daily-report 방식). 쿼터 때문에 멈춘 경우도 `ok`다.
- `daily.yml`은 krx-daily-report의 `daily-report.yml` 구조를 따른다.
  - `on`: `schedule: cron "0 22 * * *"`, `workflow_dispatch`(입력 `date`)
  - 권한: `contents: write`, `issues: write`, `pages: write`, `id-token: write`
  - `concurrency: group: dartbot, cancel-in-progress: false`
  - 시크릿 3개를 env로 넘긴다.
  - 커밋 단계: `git add data` → `git diff --cached --quiet ||` commit `"data: <date>"` → `git pull --rebase origin main` → `git push`
  - 배포 단계: `actions/upload-pages-artifact@v3`(path `site`) → `actions/deploy-pages@v4`
    - environment는 `github-pages`다. 배포는 같은 job 안의 step으로 둬서 job 하나로 끝낸다.
  - `if: failure()`이면 Issue를 만든다. 라벨은 `dartbot-failure`, 본문에 실행 로그 URL을 넣는다.
- `backfill.yml`
  - `workflow_dispatch` 입력 `start`, `end`
  - `timeout-minutes: 180`
  - `concurrency` 그룹은 daily와 같다.
  - 커밋 메시지는 `"data: backfill <start>-<end>"`

- [ ] **Step 1: 테스트 작성.** 가짜 클라이언트들을 주입하고 `tmp_path`를 쓴다.
  - `test_daily_catches_up_missed_days`: `last_collected_date`가 today−3이면 2일 치를 수집하고, 상태는 today−1이 된다.
  - `test_daily_first_run_collects_yesterday_only`
  - `test_backfill_does_not_move_state`
  - `test_daily_quota_stop_is_not_failure`: 종료 코드 0, `GITHUB_OUTPUT` 파일에 `status=ok`
  - `test_rerun_same_day_no_duplicates` (Review Focus 5): `daily`를 같은 today로 두 번 실행해도 공시와 분류 건수가 같다.
  - `test_cli_missing_key_exits_2_with_message`
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.**
- [ ] **Step 4: 통과 확인.** `pytest tests/test_pipeline_cli.py -v` → PASS
- [ ] **Step 5: 전체 테스트와 커버리지 확인.** `pytest -q --cov=dartbot --cov-fail-under=80` → PASS, 80% 이상
- [ ] **Step 6: 로컬 실제 실행 (수동, 키 3개 필요).**
  - `python -m dartbot daily --date 20261124`를 실행한다. 분류는 `--max-requests 2` 수준으로 작게 두려면 `classify`를 따로 실행한다.
  - `data/`에 파일이 생기고 `site/`가 만들어지는지 확인한다.
- [ ] **Step 7: 커밋.** `feat: daily/backfill pipeline, CLI, and GitHub workflows`

### Task 13: GitHub 배포와 1년 소급 실행 (수동 단계 포함)

**Files:**
- Create: `README.md`
- Modify: `src/dartbot/config.py`. `LIVE_START_DATE`를 daily 예약 실행을 켜는 날로 확정한다.

- [ ] **Step 1: README 작성.** 스펙 4.10의 순서를 따른다.
  1. 문제 정의
  2. 구조도(mermaid)
  3. 핵심 결과: 대시보드 링크. 수치는 Step 7에서 채운다.
  4. 검증 방법: CAR 정의, FLUC_RT를 쓰는 이유, 적중 판정, live/backfill 분리 이유
  5. 한계
     - 표본 크기
     - 시장조정 모델의 단순함
     - backfill 미래 정보 혼입과 마스킹 완화
     - 무료 모델 품질
     - 키워드 필터의 누락
     - 60일 비활성 시 예약 실행 중지
  6. 실행 방법
     - 키 3개 발급
     - KRX 서비스 신청 목록: 유가증권·코스닥 일별매매정보, KOSPI·KOSDAQ 지수
     - Secrets 등록
     - Pages 소스를 "GitHub Actions"로 설정
     - backfill을 3개월씩 나눠 실행하는 이유: DART 일 2만 회 한도
  7. 향후 계획
  - 커밋: `docs: README`
- [ ] **Step 2: 사용자 작업.**
  - GitHub 공개 저장소를 만든다.
  - Secrets 3개(`DART_API_KEY`, `GEMINI_API_KEY`, `KRX_API_KEY`)를 등록한다.
  - Settings → Pages → Source를 "GitHub Actions"로 설정한다.
  - 원격 추가와 push는 사용자 확인을 받은 뒤에만 한다.
- [ ] **Step 3: backfill 실행.** Actions에서 backfill을 4번 수동 실행한다.
  - `20251124`–`20260223`
  - `20260224`–`20260523`
  - `20260524`–`20260823`
  - `20260824`–`20261123`
  - 각 실행이 끝나면 `git pull` 후 확인한다.
    - `data/disclosures`의 월별 파일 수
    - `data/prices/stocks`의 거래일 수(1년에 약 245일)
- [ ] **Step 4: daily 켜기.**
  - `LIVE_START_DATE`를 오늘 날짜로 커밋한다.
  - daily를 `workflow_dispatch`로 한 번 실행해서 다음을 확인한다.
    - Pages 사이트가 열린다.
    - 운영 현황의 "남은 대기열"이 첫 실행 분류량만큼 줄었다.
  - 하루 처리량으로 1년 치 분류 완료 예상일을 계산해서 README에 적는다.
- [ ] **Step 5: 대기열이 0이 될 때까지 매일 자동 실행.** 이 기간에 사용자가 할 일은 없다. 실패하면 Issue가 생긴다.
- [ ] **Step 6: 결과 점검.** backfill 그룹의 summary를 보고 이상값을 점검한다.
  - `|CAR[1]| > 0.3`인 이벤트를 뽑아 권리락, 거래정지 해제 같은 데이터 문제인지 원문과 대조한다.
  - 데이터 문제가 발견되면 해당 Task로 돌아가 테스트를 추가하고 고친다.
- [ ] **Step 7: 결과 확정.** README 핵심 결과를 채운다.
  - 유형별 평균 CAR과 표본 수
  - 방향 적중률
  - 유의한 것(p<0.05)과 유의하지 않은 것을 구분해서 적는다.
  - 커밋: `docs: first 1-year backfill results`
