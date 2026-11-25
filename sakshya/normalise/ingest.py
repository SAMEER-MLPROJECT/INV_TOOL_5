from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from sakshya.adapters import ADAPTERS, AdapterContext
from sakshya.core.config import colmap
from sakshya.core.identifiers import canonical_phone
from sakshya.custody.intake import Evidence

OBS_COLUMNS = [
    "obs_id",
    "evidence_id",
    "file",
    "source",
    "kind",
    "row",
    "t_raw",
    "t",
    "sigma_t",
    "lat",
    "lon",
    "radius_m",
    "place",
    "amount",
    "direction",
    "duration_s",
    "text",
    "raw",
    "anchors",
    "attrs",
    "domain",
]
ID_COLUMNS = ["obs_id", "role", "kind", "value", "entity"]


@dataclass
class Intake:
    obs: pd.DataFrame
    ids: pd.DataFrame
    towers: dict[str, dict[str, Any]]
    atms: dict[str, dict[str, Any]]
    warnings: dict[str, list[str]]
    subjects: dict[str, list[tuple[str, str]]]
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)


def _domain(evidence: Evidence, settings: dict[str, Any]) -> str:
    if evidence.entry.get("clock_domain"):
        return str(evidence.entry["clock_domain"])
    if settings.get("clock_domain") == "export":
        owner = canonical_phone(evidence.entry.get("owner", "")) or evidence.entry.get("owner", "")
        return f"export:{owner}"
    return evidence.evidence_id


def ingest(case_dir: Path, evidence: list[Evidence]) -> Intake:
    obs_rows: list[dict[str, Any]] = []
    id_rows: list[dict[str, Any]] = []
    towers: dict[str, dict[str, Any]] = {}
    atms: dict[str, dict[str, Any]] = {}
    warnings: dict[str, list[str]] = {}
    subjects: dict[str, list[tuple[str, str]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    for item in evidence:
        settings = colmap(item.source, item.entry.get("colmap"))
        ctx = AdapterContext(case_dir / item.file, item.evidence_id, item.entry, settings)
        try:
            result = ADAPTERS[item.source](ctx)
        except Exception as exc:
            warnings[item.evidence_id] = [f"Could not parse file: {exc}"]
            continue
        towers.update(result.towers)
        atms.update(result.atms)
        if result.warnings:
            warnings[item.evidence_id] = result.warnings
        subjects[item.evidence_id] = result.meta.get("subject", [])
        meta[item.evidence_id] = result.meta
        domain = _domain(item, settings)
        default_sigma = float(settings.get("sigma_s", 60))
        for record in result.records:
            obs_id = f"{item.evidence_id}:{record.row}"
            obs_rows.append(
                {
                    "obs_id": obs_id,
                    "evidence_id": item.evidence_id,
                    "file": item.file,
                    "source": item.source,
                    "kind": record.kind,
                    "row": record.row,
                    "t_raw": record.t_raw,
                    "t": record.t_raw,
                    "sigma_t": record.sigma_t if record.sigma_t is not None else default_sigma,
                    "lat": record.lat,
                    "lon": record.lon,
                    "radius_m": record.radius_m,
                    "place": record.place,
                    "amount": record.amount,
                    "direction": record.direction,
                    "duration_s": record.duration_s,
                    "text": record.text,
                    "raw": record.raw,
                    "anchors": list(record.anchors),
                    "attrs": dict(record.attrs),
                    "domain": domain,
                }
            )
            seen = set()
            for role, kind, value in record.ids:
                key = (role, kind, value)
                if key in seen:
                    continue
                seen.add(key)
                id_rows.append({"obs_id": obs_id, "role": role, "kind": kind, "value": value, "entity": f"{kind}:{value}"})
    obs = pd.DataFrame(obs_rows, columns=OBS_COLUMNS)
    ids = pd.DataFrame(id_rows, columns=ID_COLUMNS)
    obs = obs.astype(
        {
            "t_raw": "float64",
            "t": "float64",
            "sigma_t": "float64",
            "lat": "float64",
            "lon": "float64",
            "radius_m": "float64",
            "amount": "float64",
            "duration_s": "float64",
        }
    )
    intake = Intake(obs, ids, towers, atms, warnings, subjects, meta)
    resolve_places(intake)
    return intake


def resolve_places(intake: Intake) -> None:
    obs = intake.obs
    if obs.empty:
        return
    cells = intake.ids[intake.ids["kind"] == "cell"].drop_duplicates("obs_id").set_index("obs_id")["value"]
    atm_ids = intake.ids[intake.ids["kind"] == "atm"].drop_duplicates("obs_id").set_index("obs_id")["value"]
    lat = obs["lat"].to_numpy(copy=True)
    lon = obs["lon"].to_numpy(copy=True)
    radius = obs["radius_m"].to_numpy(copy=True)
    place = obs["place"].to_numpy(copy=True)
    for position, obs_id in enumerate(obs["obs_id"].to_numpy()):
        if not pd.isna(lat[position]):
            continue
        site = None
        label = None
        if obs_id in cells.index:
            site = intake.towers.get(cells[obs_id])
            label = cells[obs_id]
        if site is None and obs_id in atm_ids.index:
            site = intake.atms.get(atm_ids[obs_id])
            label = atm_ids[obs_id]
        if site is not None:
            lat[position] = site["lat"]
            lon[position] = site["lon"]
            radius[position] = site["radius_m"]
            place[position] = site.get("label") or label
    obs["lat"] = lat
    obs["lon"] = lon
    obs["radius_m"] = radius
    obs["place"] = place
