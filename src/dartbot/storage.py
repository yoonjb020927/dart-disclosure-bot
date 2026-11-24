"""File storage: monthly JSONL for records, a small JSON state file."""
from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import Classification, Disclosure

DISCLOSURES = "disclosures"
CLASSIFICATIONS = "classifications"
STATE_FILE = "state.json"
OPS_LOG = "ops_log.jsonl"


def _month_path(root: Path, kind: str, yyyymmdd: str) -> Path:
    return root / kind / yyyymmdd[:4] / f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}.jsonl"


def _iter_jsonl(paths: Iterable[Path]) -> Iterator[dict]:
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def _all_files(root: Path, kind: str) -> list[Path]:
    base = root / kind
    return sorted(base.glob("*/*.jsonl")) if base.exists() else []


def _append(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _group_by_month(items: list, date_of) -> dict[str, list]:
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(date_of(item)[:6], []).append(item)
    return groups


def append_disclosures(items: list[Disclosure], root: Path) -> int:
    seen = {row["rcept_no"] for row in _iter_jsonl(_all_files(root, DISCLOSURES))}
    fresh: list[Disclosure] = []
    for d in items:
        if d.rcept_no not in seen:
            seen.add(d.rcept_no)
            fresh.append(d)
    for month, group in _group_by_month(fresh, lambda d: d.rcept_dt).items():
        _append(_month_path(root, DISCLOSURES, month + "01"), [d.to_dict() for d in group])
    return len(fresh)


def load_disclosures(root: Path, start: str | None = None, end: str | None = None) -> list[Disclosure]:
    out, seen = [], set()
    for row in _iter_jsonl(_all_files(root, DISCLOSURES)):
        dt = row["rcept_dt"]
        if row["rcept_no"] in seen:  # a git merge can duplicate lines
            continue
        seen.add(row["rcept_no"])
        if (start is None or dt >= start) and (end is None or dt <= end):
            out.append(Disclosure.from_dict(row))
    return out


def append_classifications(items: list[Classification], root: Path) -> int:
    seen = {
        (row["rcept_no"], row["classifier_version"])
        for row in _iter_jsonl(_all_files(root, CLASSIFICATIONS))
    }
    fresh: list[Classification] = []
    for c in items:
        key = (c.rcept_no, c.classifier_version)
        if key not in seen:
            seen.add(key)
            fresh.append(c)
    # DART rcept_no starts with the filing date (YYYYMMDD).
    for month, group in _group_by_month(fresh, lambda c: c.rcept_no[:8]).items():
        _append(_month_path(root, CLASSIFICATIONS, month + "01"), [c.to_dict() for c in group])
    return len(fresh)


def load_classifications(root: Path) -> list[Classification]:
    out, seen = [], set()
    for row in _iter_jsonl(_all_files(root, CLASSIFICATIONS)):
        key = (row["rcept_no"], row["classifier_version"])
        if key not in seen:  # a git merge can duplicate lines
            seen.add(key)
            out.append(Classification.from_dict(row))
    return out


def read_state(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        return {"last_collected_date": None}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, root / STATE_FILE)


def append_ops_log(root: Path, record: dict) -> None:
    _append(root / OPS_LOG, [record])


def load_ops_log(root: Path) -> list[dict]:
    path = root / OPS_LOG
    return list(_iter_jsonl([path])) if path.exists() else []
