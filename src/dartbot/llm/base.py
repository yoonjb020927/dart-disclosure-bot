"""Classifier contract shared by every LLM backend."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class QuotaExceeded(RuntimeError):
    """The provider's rate or daily quota is used up; stop for today."""


@dataclass(frozen=True)
class ClassifierInput:
    """One filing, already masked."""

    rcept_no: str
    title: str
    body: str


@dataclass(frozen=True)
class ClassifierOutput:
    rcept_no: str
    summary: tuple[str, str, str]
    type: str
    sentiment: str
    confidence: float
    rationale: str


class Classifier(Protocol):
    version: str

    def classify_batch(self, items: list[ClassifierInput]) -> tuple[list[ClassifierOutput], list[str]]:
        """Return (successes, rcept_nos that failed)."""
        ...
