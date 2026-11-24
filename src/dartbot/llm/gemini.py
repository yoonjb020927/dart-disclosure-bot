"""Gemini backend: batched structured output, validation, single-item retry."""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable

from .. import config
from .base import ClassifierInput, ClassifierOutput, QuotaExceeded
from .prompt import PROMPT_VERSION, RESPONSE_SCHEMA, build_prompt

log = logging.getLogger(__name__)


def _is_quota_error(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def _parse_item(raw: dict) -> ClassifierOutput | None:
    try:
        summary = tuple(str(s) for s in raw["summary"])
        confidence = float(raw["confidence"])
        if (
            len(summary) != 3
            or raw["type"] not in config.TYPES
            or raw["sentiment"] not in config.SENTIMENTS
            or not 0.0 <= confidence <= 1.0
        ):
            return None
        return ClassifierOutput(
            rcept_no=str(raw["rcept_no"]),
            summary=summary,  # type: ignore[arg-type]
            type=raw["type"],
            sentiment=raw["sentiment"],
            confidence=confidence,
            rationale=str(raw["rationale"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


class GeminiClassifier:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = config.GEMINI_MODEL,
        client=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client is None:
            from google import genai

            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set. Put it in .env or GitHub Secrets.")
            client = genai.Client(api_key=key)
        self._client = client
        self._model = model
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self.version = f"{model}+{PROMPT_VERSION}"

    def classify_batch(self, items: list[ClassifierInput]) -> tuple[list[ClassifierOutput], list[str]]:
        results, failed = self._call(items)
        if len(items) > 1 and failed:
            by_id = {i.rcept_no: i for i in items}
            still_failed = []
            for rcept_no in failed:
                single_ok, single_failed = self._call([by_id[rcept_no]])
                results.update(single_ok)
                still_failed.extend(single_failed)
            failed = still_failed
        return list(results.values()), failed

    def _call(self, items: list[ClassifierInput]) -> tuple[dict[str, ClassifierOutput], list[str]]:
        wanted = [i.rcept_no for i in items]
        self._wait_for_rate_limit()
        try:
            resp = self._client.models.generate_content(
                model=self._model,
                contents=build_prompt(items),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": RESPONSE_SCHEMA,
                    "temperature": 0,
                },
            )
            raw_items = json.loads(resp.text)
        except Exception as exc:  # provider errors vary; quota is the only one that stops the run
            if _is_quota_error(exc):
                raise QuotaExceeded(str(exc)) from exc
            log.warning("Gemini call failed for %d item(s): %s", len(items), exc)
            return {}, wanted
        parsed = [_parse_item(r) for r in raw_items] if isinstance(raw_items, list) else []
        results = {p.rcept_no: p for p in parsed if p is not None and p.rcept_no in wanted}
        return results, [r for r in wanted if r not in results]

    def _wait_for_rate_limit(self) -> None:
        gap = 60.0 / config.REQUESTS_PER_MINUTE
        if self._last_call is not None:
            elapsed = self._clock() - self._last_call
            if elapsed < gap:
                self._sleep(gap - elapsed)
        self._last_call = self._clock()
