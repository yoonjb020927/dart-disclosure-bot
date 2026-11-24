"""Immutable records that flow through the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from . import config


def _require(value: str, allowed: tuple[str, ...], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"{field}={value!r} is not one of {allowed}")


@dataclass(frozen=True)
class Disclosure:
    rcept_no: str
    rcept_dt: str
    corp_code: str
    corp_name: str
    stock_code: str
    corp_cls: str
    report_nm: str
    is_correction: bool
    candidate_type: str | None

    def __post_init__(self) -> None:
        if self.candidate_type is not None:
            _require(self.candidate_type, config.TYPES, "candidate_type")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Disclosure:
        return cls(**d)


@dataclass(frozen=True)
class Classification:
    rcept_no: str
    summary: tuple[str, str, str]
    type: str
    sentiment: str
    confidence: float
    rationale: str
    classifier_version: str
    origin: str
    input_mode: str
    classified_at: str

    def __post_init__(self) -> None:
        _require(self.type, config.TYPES, "type")
        _require(self.sentiment, config.SENTIMENTS, "sentiment")
        _require(self.origin, config.ORIGINS, "origin")
        _require(self.input_mode, config.INPUT_MODES, "input_mode")
        if len(self.summary) != 3:
            raise ValueError("summary must have exactly 3 sentences")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence={self.confidence} outside [0, 1]")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["summary"] = list(self.summary)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Classification:
        return cls(**{**d, "summary": tuple(d["summary"])})


@dataclass(frozen=True)
class EventResult:
    rcept_no: str
    t0: str | None
    car: dict[int, float | None]
    status: str
    source: str

    def __post_init__(self) -> None:
        _require(self.status, config.EVENT_STATUSES, "status")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["car"] = {str(k): v for k, v in self.car.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EventResult:
        return cls(**{**d, "car": {int(k): v for k, v in d["car"].items()}})
