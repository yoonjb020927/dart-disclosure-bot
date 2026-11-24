"""Prompt text. Bump PROMPT_VERSION on any wording change: results are grouped by it."""
from __future__ import annotations

import json

from .. import config
from .base import ClassifierInput

PROMPT_VERSION = "p1"

TYPE_GUIDE = {
    "유상증자": "새 주식을 발행해 자금을 조달 (유무상 동시 포함)",
    "무상증자": "주주에게 새 주식을 무상으로 배정",
    "자기주식 취득": "회사가 자기 주식을 매입하거나 신탁계약 체결",
    "자기주식 처분": "보유한 자기 주식을 매각·교부",
    "자기주식 소각": "주식을 소각해 발행주식 수를 줄임",
    "단일판매·공급계약": "수주, 판매·공급 계약 체결",
    "최대주주 변경": "최대주주가 바뀌거나 바뀌는 계약 체결",
    "전환사채·신주인수권부사채 발행": "CB 또는 BW 발행",
    "합병·분할": "합병, 분할, 분할합병",
    "영업(잠정)실적": "잠정 실적 발표, 매출·손익 구조 변경",
    "기타": "위 어느 것에도 해당하지 않음",
}

INSTRUCTIONS = """너는 한국 주식시장 공시 분석가다.
아래 공시들을 각각 분석해서 JSON 배열로만 답하라. 배열의 각 원소는 입력 공시 하나에 대응한다.

규칙:
- rcept_no는 입력값을 그대로 되돌린다.
- summary는 한국어 정확히 3문장의 배열이다. 회사는 "A사"로, 날짜는 "[날짜]"로 둔 채 쓴다.
- type은 아래 유형 중 하나다.
- sentiment는 기존 주주 입장에서 공시 직후 1~2거래일 주가에 미칠 방향이다: 긍정, 부정, 중립 중 하나.
- confidence는 sentiment 판단의 확신도 0~1이다.
- rationale은 판단 근거 한 문장이다.
- 입력에 없는 정보(회사 이름, 과거 주가, 뉴스)를 추측하지 않는다.

유형:
{types}

공시:
{items}
"""


def build_prompt(items: list[ClassifierInput]) -> str:
    types = "\n".join(f"- {t}: {TYPE_GUIDE[t]}" for t in config.TYPES)
    payload = [{"rcept_no": i.rcept_no, "title": i.title, "body": i.body} for i in items]
    return INSTRUCTIONS.format(types=types, items=json.dumps(payload, ensure_ascii=False, indent=1))


RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "rcept_no": {"type": "STRING"},
            "summary": {"type": "ARRAY", "items": {"type": "STRING"}},
            "type": {"type": "STRING", "enum": list(config.TYPES)},
            "sentiment": {"type": "STRING", "enum": list(config.SENTIMENTS)},
            "confidence": {"type": "NUMBER"},
            "rationale": {"type": "STRING"},
        },
        "required": ["rcept_no", "summary", "type", "sentiment", "confidence", "rationale"],
    },
}
