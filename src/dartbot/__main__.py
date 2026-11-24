"""CLI: python -m dartbot <command>."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, pipeline

KEYS = {"dart": "DART_API_KEY", "krx": "KRX_API_KEY", "gemini": "GEMINI_API_KEY"}
NEEDS = {
    "daily": {"dart", "krx", "gemini"},
    "backfill": {"dart", "krx"},
    "classify": {"dart", "gemini"},
    "backtest": set(),
    "site": set(),
}


class MissingKeys(RuntimeError):
    pass


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv()


def build_clients(needs: set[str]):
    missing = [KEYS[n] for n in sorted(needs) if not os.environ.get(KEYS[n])]
    if missing:
        raise MissingKeys(", ".join(missing))
    from .dart_client import DartClient
    from .krx_client import KrxClient
    from .llm.gemini import GeminiClassifier

    return (
        DartClient() if "dart" in needs else None,
        KrxClient() if "krx" in needs else None,
        GeminiClassifier() if "gemini" in needs else None,
    )


def _github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for k, v in values.items():
                fh.write(f"{k}={v}\n")


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", type=Path, default=config.DATA_DIR, help="data directory")
    p = argparse.ArgumentParser(prog="dartbot", description="DART 공시 요약·분류봇")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("daily", parents=[common], help="수집 → 분류 → 백테스트 → 사이트")
    d.add_argument("--date", help="YYYYMMDD, 오늘로 간주할 날짜 (기본: 오늘 KST)")
    b = sub.add_parser("backfill", parents=[common], help="기간의 공시·주가만 수집 (분류는 daily가 대기열로 처리)")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    c = sub.add_parser("classify", parents=[common], help="대기열 분류만 실행")
    c.add_argument("--max-requests", type=int, default=config.DAILY_REQUEST_CAP)
    sub.add_parser("backtest", parents=[common], help="백테스트·요약·사이트만 다시 생성")
    sub.add_parser("site", parents=[common], help="사이트만 다시 생성")
    pr = sub.add_parser("probe", parents=[common], help="실제 API 연결 확인")
    pr.add_argument("target", choices=sorted(KEYS))
    pr.add_argument("--date", default="20261120")
    return p


def _probe(target: str, day: str) -> None:
    dart, krx, clf = build_clients({target})
    if target == "dart":
        rows = dart.list_disclosures(day, "Y", "B")
        print(f"{day} 유가증권 주요사항보고: {len(rows)}건")
        for r in rows[:5]:
            print(" -", r["corp_name"], r["report_nm"])
        if rows:
            print(dart.document_text(rows[0]["rcept_no"], 300))
    elif target == "krx":
        for kind in config.KRX_ENDPOINTS:
            rows = krx.fetch(kind, day)
            print(f"{kind}: {len(rows)} rows; keys={list(rows[0]) if rows else []}")
    else:
        from .llm.base import ClassifierInput

        sample = ClassifierInput("probe1", "주요사항보고서(자기주식취득결정)",
                                 "A사는 보통주 100만주를 장내매수 방식으로 취득하기로 결정했다. 취득예정금액 500억원.")
        ok, failed = clf.classify_batch([sample])
        print(clf.version, json.dumps([o.__dict__ for o in ok], ensure_ascii=False, indent=1), "failed:", failed)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parser().parse_args(argv)
    _load_env()
    root: Path = args.data
    try:
        if args.command == "probe":
            _probe(args.target, args.date)
            return 0
        dart, krx, clf = build_clients(NEEDS[args.command])
        if args.command == "daily":
            today = (
                datetime.strptime(args.date, "%Y%m%d").date()
                if args.date
                else datetime.now(ZoneInfo(config.TIMEZONE)).date()
            )
            result = pipeline.daily(root, today, dart, krx, clf)
            _github_output(status="ok", date=result["end"])
        elif args.command == "backfill":
            result = pipeline.backfill(root, args.start, args.end, dart, krx)
            _github_output(status="ok", date=args.end)
        elif args.command == "classify":
            from .classify_runner import run_classification

            result = run_classification(
                root, dart, clf, args.max_requests, lambda: datetime.now(ZoneInfo(config.TIMEZONE))
            )
        else:  # backtest / site
            result = {"events": pipeline.refresh_results(root)} if args.command == "backtest" else None
            if args.command == "site":
                from .site.build import build_site

                build_site(root, config.SITE_DIR)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except MissingKeys as exc:
        print(f"필요한 API 키가 없습니다: {exc}. .env 파일이나 GitHub Secrets에 넣어 주세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
