from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sakshya import __version__
from sakshya.core.identifiers import display
from sakshya.core.timeutil import fmt_ist
from sakshya.custody.ledger import Ledger
from sakshya.pipeline import Analysis
from sakshya.views import observation_detail

TEMPLATES = Path(__file__).resolve().parent / "templates"


def inr(value: float | None) -> str:
    if value is None:
        return ""
    whole = f"{int(round(value))}"
    negative = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return ("-" if negative else "") + "Rs " + whole


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True
    )
    env.filters["ist"] = lambda v: fmt_ist(v) if v else ""
    env.filters["inr"] = inr
    env.filters["show"] = display
    env.filters["w"] = lambda v: f"{v:+.2f}" if isinstance(v, (int, float)) else ""
    env.filters["pct"] = lambda v: f"{v * 100:.1f}%" if isinstance(v, (int, float)) else ""
    return env


def render_report(analysis: Analysis, data: dict[str, Any]) -> str:
    links = {link["link_id"]: link for link in data["links"]}
    crime = next((h for h in data["hypotheses"] if h["template"] == data["decision"]["label"]), None)
    relied: list[dict[str, Any]] = []
    if crime:
        for link_id in crime.get("links_used", []):
            if link_id in links:
                relied.append(links[link_id])
        for person in data["people"]:
            if person["roles"]:
                for member in person["members"]:
                    if member["via"] in links and links[member["via"]]["status"] in {"inferred", "confirmed"}:
                        relied.append(links[member["via"]])
    seen = set()
    relied = [l for l in relied if not (l["link_id"] in seen or seen.add(l["link_id"]))]
    phase_events = []
    if crime:
        for phase in crime["phases"]:
            details = [observation_detail(analysis, obs_id) for obs_id in phase["events"][:6]]
            phase_events.append({"phase": phase, "events": [d for d in details if d]})
    evidence_by_id = {item["evidence_id"]: item for item in data["evidence"]["items"]}
    intake_seq = {
        entry["payload"].get("file"): entry["seq"]
        for entry in Ledger(analysis.case_dir / "ledger.jsonl").entries()
        if entry["type"] == "intake"
    }
    cleared = [l for l in data["links"] if l["type"] == "impossibility" and l["status"] in {"inferred", "confirmed"}]
    rejected = [l for l in data["links"] if l["status"] == "rejected"]
    context = {
        "data": data,
        "crime": crime,
        "relied": relied,
        "phase_events": phase_events,
        "evidence_by_id": evidence_by_id,
        "intake_seq": intake_seq,
        "cleared": cleared,
        "rejected": rejected,
        "version": __version__,
        "generated": fmt_ist(time.time(), seconds=False),
        "alternatives": [h for h in data["hypotheses"] if h is not crime][:5],
    }
    return _environment().get_template("report.html").render(**context)
