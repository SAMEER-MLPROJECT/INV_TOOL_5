from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from sakshya.core.config import config_file


@dataclass
class Term:
    name: str
    w: float
    source: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Link:
    link_id: str
    type: str
    a: str
    b: str
    a_kind: str
    b_kind: str
    claim: str
    terms: list[Term] = field(default_factory=list)
    w: float = 0.0
    raw_w: float = 0.0
    prior_odds: float | None = None
    basis: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    status: str = "inferred"
    alternatives: list[str] = field(default_factory=list)
    defeaters: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    scale: float = 1.0

    @property
    def w_calibrated(self) -> float:
        return self.w * self.scale

    @property
    def lr(self) -> float:
        return 10.0 ** max(-12.0, min(12.0, self.w_calibrated))

    @property
    def posterior(self) -> float | None:
        if self.prior_odds is None:
            return None
        odds = self.prior_odds * self.lr
        return odds / (1.0 + odds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "type": self.type,
            "a": self.a,
            "b": self.b,
            "a_kind": self.a_kind,
            "b_kind": self.b_kind,
            "claim": self.claim,
            "terms": [t.to_dict() for t in self.terms],
            "w": round(self.w, 3),
            "raw_w": round(self.raw_w, 3),
            "w_calibrated": round(self.w_calibrated, 3),
            "calibration_scale": self.scale,
            "lr": self.lr,
            "verbal": verbal(self.w_calibrated),
            "prior_odds": self.prior_odds,
            "posterior": self.posterior,
            "basis": self.basis,
            "sources": self.sources,
            "status": self.status,
            "alternatives": self.alternatives,
            "defeaters": self.defeaters,
            "extra": self.extra,
            "note": self.note,
        }


def make_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def verbal(w: float) -> str:
    scale = config_file("verbal_scale.yaml")
    if w < 0:
        for band in scale["against"]:
            if -w <= math.log10(band["max_lr"]):
                return band["label"]
        return scale["against"][-1]["label"]
    for band in scale["support"]:
        if w <= math.log10(band["max_lr"]):
            return band["label"]
    return scale["support"][-1]["label"]


@dataclass
class ClockEstimate:
    evidence_id: str
    domain: str
    offset_s: float
    sigma_s: float
    anchors: int
    method: str
    note: str
    reference: bool = False
    timezone_shift: bool = False
    drift_per_day_s: float = 0.0
    drift_anchor_t: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Person:
    person_id: str
    members: dict[str, float]
    via: dict[str, str]
    names: list[str]
    label: str
    is_seed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
