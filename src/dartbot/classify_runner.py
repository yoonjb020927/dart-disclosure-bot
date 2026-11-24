"""Work through the classification queue within today's request budget."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import config, storage
from .dart_client import DartApiError, DartClient
from .llm.base import Classifier, ClassifierInput, QuotaExceeded
from .masking import mask_text
from .models import Classification, Disclosure

log = logging.getLogger(__name__)


def origin_of(d: Disclosure) -> str:
    return "live" if d.rcept_dt >= config.LIVE_START_DATE else "backfill"


def pending_queue(
    disclosures: list[Disclosure], classifications: list[Classification], version: str
) -> list[Disclosure]:
    done = {c.rcept_no for c in classifications if c.classifier_version == version}
    todo = [
        d for d in disclosures if d.candidate_type and not d.is_correction and d.rcept_no not in done
    ]
    # live first, then backfill; newest first inside each group.
    return sorted(todo, key=lambda d: (origin_of(d) == "live", d.rcept_dt, d.rcept_no), reverse=True)


def _prepare(d: Disclosure, dart: DartClient) -> tuple[ClassifierInput, str]:
    try:
        body, mode = dart.document_text(d.rcept_no, config.BODY_MAX_CHARS), "body"
    except DartApiError as exc:
        log.warning("body unavailable for %s, using title only: %s", d.rcept_no, exc)
        body, mode = "", "title_only"
    masked = ClassifierInput(
        rcept_no=d.rcept_no,
        title=mask_text(d.report_nm, d.corp_name, d.stock_code),
        body=mask_text(body, d.corp_name, d.stock_code),
    )
    return masked, mode


def run_classification(
    root: Path,
    dart: DartClient,
    classifier: Classifier,
    max_requests: int,
    now: Callable[[], datetime],
) -> dict:
    queue = pending_queue(
        storage.load_disclosures(root), storage.load_classifications(root), classifier.version
    )
    classified = failed = 0
    stopped = False
    size = config.BATCH_SIZE
    for start in range(0, min(len(queue), max_requests * size), size):
        batch = queue[start : start + size]
        prepared = {d.rcept_no: (d, *_prepare(d, dart)) for d in batch}
        try:
            outputs, failed_ids = classifier.classify_batch([p[1] for p in prepared.values()])
        except QuotaExceeded as exc:
            log.warning("quota reached, stopping for today: %s", exc)
            stopped = True
            break
        stamp = now().isoformat()
        records = [
            Classification(
                rcept_no=o.rcept_no,
                summary=o.summary,
                type=o.type,
                sentiment=o.sentiment,
                confidence=o.confidence,
                rationale=o.rationale,
                classifier_version=classifier.version,
                origin=origin_of(prepared[o.rcept_no][0]),
                input_mode=prepared[o.rcept_no][2],
                classified_at=stamp,
            )
            for o in outputs
        ]
        classified += storage.append_classifications(records, root)
        failed += len(failed_ids)
    return {
        "classified": classified,
        "failed": failed,
        "remaining": len(queue) - classified,
        "stopped_by_quota": stopped,
    }
