"""Thin client for the OpenDART API (list.json, document.xml)."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import zipfile

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
PAGE_COUNT = 100
REQUEST_RETRIES = 3
REQUEST_TIMEOUT_SEC = 30
STATUS_OK = "000"
STATUS_NO_DATA = "013"

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


NO_DOCUMENT_STATUSES = ("013", "014")  # the filing has no document: title only is the best we can do
STATUS_LIMIT = "020"  # daily request limit reached


class DartApiError(RuntimeError):
    """OpenDART returned an error status or an unreadable payload. status is None for transport errors."""

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class DartClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        key = api_key or os.environ.get("DART_API_KEY")
        if not key:
            raise DartApiError("DART_API_KEY is not set. Put it in .env or GitHub Secrets.")
        self._key = key
        self._session = session or requests.Session()

    def list_disclosures(self, date: str, corp_cls: str, pblntf_ty: str) -> list[dict]:
        """All filings for one day / market / filing type, across every page."""
        rows: list[dict] = []
        page, total = 1, 1
        while page <= total:
            payload = self._get_json(
                "list.json",
                {
                    "bgn_de": date,
                    "end_de": date,
                    "corp_cls": corp_cls,
                    "pblntf_ty": pblntf_ty,
                    "page_no": page,
                    "page_count": PAGE_COUNT,
                },
            )
            status = payload.get("status")
            if status == STATUS_NO_DATA:
                return []
            if status != STATUS_OK:
                raise DartApiError(
                    f"list.json {date} {corp_cls}/{pblntf_ty}: {status} {payload.get('message')}", status=status
                )
            rows.extend(payload.get("list", []))
            total = int(payload.get("total_page", 1))
            page += 1
        return rows

    def document_text(self, rcept_no: str, max_chars: int) -> str:
        """Plain text of the original filing, tags stripped, cut to max_chars."""
        content = self._get("document.xml", {"rcept_no": rcept_no}).content
        if not zipfile.is_zipfile(io.BytesIO(content)):
            try:
                payload = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise DartApiError(f"document.xml {rcept_no}: not a zip") from None
            raise DartApiError(
                f"document.xml {rcept_no}: {payload.get('status')} {payload.get('message')}",
                status=payload.get("status"),
            )
        parts = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                parts.append(_decode(zf.read(name)))
        text = _SPACE.sub(" ", _TAG.sub(" ", " ".join(parts))).strip()
        return text[:max_chars]

    def _get_json(self, endpoint: str, params: dict) -> dict:
        try:
            return self._get(endpoint, params).json()
        except ValueError as exc:
            raise DartApiError(f"{endpoint}: invalid JSON response") from exc

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        url = f"{BASE_URL}/{endpoint}"
        last_error: Exception | None = None
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                resp = self._session.get(
                    url, params={"crtfc_key": self._key, **params}, timeout=REQUEST_TIMEOUT_SEC
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_error = exc
                log.warning("DART request failed (attempt %d): %s", attempt, exc)
                time.sleep(2 * attempt)
        raise DartApiError(f"DART request failed after retries: {last_error}")


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")
