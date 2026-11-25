from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any

from sakshya.core.identifiers import canonical
from sakshya.core.timeutil import parse_local, tz_from_spec

UPI_PATTERN = re.compile(r"\b[a-zA-Z0-9._\-]{2,64}@[a-zA-Z][a-zA-Z0-9.\-]{1,32}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")
URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
AMOUNT_PATTERN = re.compile(r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)


@dataclass
class Record:
    row: int
    kind: str
    t_raw: float | None
    raw: str
    ids: list[tuple[str, str, str]] = field(default_factory=list)
    sigma_t: float | None = None
    lat: float | None = None
    lon: float | None = None
    radius_m: float | None = None
    place: str = ""
    amount: float | None = None
    direction: str = ""
    duration_s: float | None = None
    text: str = ""
    anchors: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def add_id(self, role: str, kind: str, value: Any) -> None:
        identifier = canonical(kind, value)
        if identifier is not None:
            self.ids.append((role, identifier.kind, identifier.value))


@dataclass
class ParseResult:
    records: list[Record] = field(default_factory=list)
    towers: dict[str, dict[str, Any]] = field(default_factory=dict)
    atms: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterContext:
    path: Path
    evidence_id: str
    entry: dict[str, Any]
    colmap: dict[str, Any]

    @property
    def tz(self) -> timezone:
        return tz_from_spec(self.colmap.get("timezone"))

    @property
    def time_format(self) -> str | None:
        return self.colmap.get("time_format")

    def column(self, name: str) -> str | None:
        return self.colmap.get("columns", {}).get(name)

    def parse_time(self, value: Any, fmt: str | None = None) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return parse_local(text, fmt or self.time_format, self.tz)


def read_rows(ctx: AdapterContext) -> Iterator[tuple[int, dict[str, str], str]]:
    with ctx.path.open("r", encoding="utf-8-sig", newline="") as handle:
        lines = handle.read().splitlines()
    if not lines:
        return
    header = next(csv.reader([lines[0]]))
    for index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        values = next(csv.reader([line]))
        row = {header[i]: values[i] if i < len(values) else "" for i in range(len(header))}
        yield index, row, line


def get(ctx: AdapterContext, row: dict[str, str], name: str) -> str:
    column = ctx.column(name)
    if column is None:
        return ""
    return str(row.get(column, "") or "").strip()


def to_float(value: str) -> float | None:
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def mentions(record: Record, text: str) -> None:
    for match in UPI_PATTERN.findall(text):
        domain = match.split("@", 1)[1]
        record.add_id("mentioned", "email" if "." in domain else "upi", match)
    for match in PHONE_PATTERN.findall(text):
        record.add_id("mentioned", "phone", match)
    for match in URL_PATTERN.findall(text):
        record.add_id("mentioned", "domain", match)
