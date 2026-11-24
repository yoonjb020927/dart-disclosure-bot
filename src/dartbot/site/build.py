"""Write the static dashboard: three HTML pages plus the JSON they read."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

from .. import config, storage
from ..backtest import latest_by_rcept, load_events
from ..classify_runner import pending_queue

TEMPLATE_DIR = Path(__file__).parent / "templates"
PAGES = ("index.html", "validation.html", "ops.html")
DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
EXCLUDED_TITLES_SHOWN = 50
MARKET_NAMES = {"Y": "유가증권", "K": "코스닥"}


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _day_rows(data_root: Path) -> dict[str, list[dict]]:
    latest = latest_by_rcept(storage.load_classifications(data_root))
    events = {e.rcept_no: e for e in load_events(data_root)}
    days: dict[str, list[dict]] = {}
    for d in storage.load_disclosures(data_root):
        if not d.candidate_type:
            continue
        c, e = latest.get(d.rcept_no), events.get(d.rcept_no)
        days.setdefault(d.rcept_dt, []).append(
            {
                "rcept_no": d.rcept_no,
                "corp_name": d.corp_name,
                "market": MARKET_NAMES.get(d.corp_cls, d.corp_cls),
                "title": d.report_nm,
                "url": DART_URL.format(d.rcept_no),
                "is_correction": d.is_correction,
                "type": c.type if c else d.candidate_type,
                "sentiment": c.sentiment if c else None,
                "summary": list(c.summary) if c else [],
                "confidence": c.confidence if c else None,
                "car1": e.car.get(config.PRIMARY_WINDOW) if e else None,
            }
        )
    return days


def _ops(data_root: Path) -> dict:
    log = storage.load_ops_log(data_root)
    disclosures = storage.load_disclosures(data_root)
    classifications = storage.load_classifications(data_root)
    runs = [r for r in log if r.get("kind") == "run"]
    versions = {c.classifier_version for c in classifications}
    current = max(versions) if versions else ""
    excluded = [d.report_nm for d in sorted(disclosures, key=lambda d: d.rcept_no, reverse=True) if not d.candidate_type]
    return {
        "last_run": runs[-1] if runs else None,
        "totals": {
            "collected": len(disclosures),
            "candidates": sum(1 for d in disclosures if d.candidate_type and not d.is_correction),
            "classified": len({c.rcept_no for c in classifications}),
            "failed_last_run": runs[-1]["failed"] if runs else 0,
            "remaining": len(pending_queue(disclosures, classifications, current)) if current else None,
        },
        "daily": [r for r in log if r.get("kind") == "collect"],
        "runs": runs[-60:],
        "excluded_titles": excluded[:EXCLUDED_TITLES_SHOWN],
    }


def build_site(data_root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    days = _day_rows(data_root)
    for day, rows in days.items():
        _write_json(out / "data" / "days" / f"{day}.json", rows)
    _write_json(out / "data" / "days" / "index.json", sorted(days, reverse=True))

    summary_path = data_root / "results" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {"groups": []}
    _write_json(out / "data" / "summary.json", summary)
    _write_json(out / "data" / "ops.json", _ops(data_root))

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    built_at = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M KST")
    for page in PAGES:
        html = env.get_template(page).render(page=page, built_at=built_at, primary_threshold=config.PRIMARY_THRESHOLD)
        (out / page).write_text(html, encoding="utf-8")
