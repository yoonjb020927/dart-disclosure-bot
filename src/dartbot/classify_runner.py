"""Work through the classification queue within today's request budget."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import config, storage
from .dart_client import NO_DOCUMENT_STATUSES, STATUS_LIMIT, DartApiError, DartClient
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


class _DartLimit(RuntimeError):
    pass


def _prepare(d: Disclosure, dart: DartClient) -> tuple[ClassifierInput, str] | None:
    """Masked input and its mode, or None when the body failed transiently (item stays queued)."""
    try:
        body, mode = dart.document_text(d.rcept_no, config.BODY_MAX_CHARS), "body"
    except DartApiError as exc:
        if exc.status == STATUS_LIMIT:
            raise _DartLimit(str(exc)) from exc
        if exc.status not in NO_DOCUMENT_STATUSES:
            log.warning("body fetch failed for %s, keeping it queued: %s", d.rcept_no, exc)
            return None
        log.warning("no document for %s, using title only: %s", d.rcept_no, exc)
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
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    queue = pending_queue(
        storage.load_disclosures(root), storage.load_classifications(root), classifier.version
    )
    classified = failed = failed_in_a_row = 0
    stopped = out_of_time = False
    size = config.BATCH_SIZE
    started = clock()
    for start in range(0, min(len(queue), max_requests * size), size):
        # leave time for backtest, site build and the commit before the workflow step timeout
        if clock() - started >= config.CLASSIFY_TIME_BUDGET_SEC:
            log.warning("time budget spent, stopping for today")
            out_of_time = True
            break
        batch = queue[start : start + size]
        try:
            prepared = {}
            for d in batch:
                ready = _prepare(d, dart)
                if ready is None:
                    failed += 1
                else:
                    prepared[d.rcept_no] = (d, *ready)
            if not prepared:
                continue
            outputs, failed_ids = classifier.classify_batch([p[1] for p in prepared.values()])
        except (QuotaExceeded, _DartLimit) as exc:
            log.warning("API limit reached, stopping for today: %s", exc)
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
        failed_in_a_row = 0 if outputs else failed_in_a_row + 1
        if failed_in_a_row >= config.MAX_FAILED_BATCHES_IN_A_ROW:
            log.warning("%d batches in a row failed, stopping for today", failed_in_a_row)
            break
    return {
        "classified": classified,
        "failed": failed,
        "remaining": len(queue) - classified,
        "stopped_by_quota": stopped,
        "stopped_by_time": out_of_time,
    }
