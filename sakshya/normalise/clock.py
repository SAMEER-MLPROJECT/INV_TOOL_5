from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import theilslopes

from sakshya.core.config import colmap, settings
from sakshya.core.timeutil import describe_duration
from sakshya.custody.intake import Evidence
from sakshya.model import ClockEstimate


def _vote(diffs: np.ndarray, tolerance: float) -> float:
    ordered = np.sort(diffs)
    best_count, best_center = -1, 0.0
    right = 0
    for left in range(len(ordered)):
        while right < len(ordered) and ordered[right] - ordered[left] <= 2 * tolerance:
            right += 1
        count = right - left
        center = float(np.median(ordered[left:right]))
        if count > best_count or (count == best_count and abs(center) < abs(best_center)):
            best_count, best_center = count, center
    return best_center


def _robust(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, max(1.4826 * mad, 1.0)


def _timezone_shift(offset: float, snap: float) -> bool:
    if abs(offset) < 1200:
        return False
    nearest = round(offset / 1800.0) * 1800.0
    return nearest != 0 and abs(offset - nearest) <= snap


def estimate_offsets(obs: pd.DataFrame, evidence: list[Evidence]) -> dict[str, ClockEstimate]:
    cfg = settings()["clock"]
    tolerance = float(cfg["vote_tolerance_s"])
    max_offset = float(cfg["max_offset_s"])
    estimates: dict[str, ClockEstimate] = {}
    reference_ids = set()
    for item in evidence:
        info = colmap(item.source, item.entry.get("colmap"))
        if info.get("reference"):
            reference_ids.add(item.evidence_id)
            estimates[item.evidence_id] = ClockEstimate(
                item.evidence_id,
                item.evidence_id,
                0.0,
                float(info.get("sigma_s", 2)),
                0,
                "reference",
                "Reference clock (system-generated record)",
                reference=True,
            )
    with_time = obs.dropna(subset=["t_raw"])
    anchor_index: dict[str, list[float]] = defaultdict(list)
    for evidence_id, anchors, t_raw in zip(with_time["evidence_id"], with_time["anchors"], with_time["t_raw"]):
        if evidence_id in reference_ids:
            for anchor in anchors:
                anchor_index[anchor].append(float(t_raw))
    domains: dict[str, list[str]] = defaultdict(list)
    domain_of = with_time.drop_duplicates("evidence_id").set_index("evidence_id")["domain"].to_dict()
    for item in evidence:
        if item.evidence_id not in reference_ids:
            domains[domain_of.get(item.evidence_id, item.evidence_id)].append(item.evidence_id)
    for domain, members in domains.items():
        rows = with_time[with_time["evidence_id"].isin(members)]
        candidates: list[tuple[int, float, float]] = []
        for position, (anchors, t_raw) in enumerate(zip(rows["anchors"], rows["t_raw"])):
            for anchor in anchors:
                for t_ref in anchor_index.get(anchor, ()):
                    diff = t_ref - float(t_raw)
                    if abs(diff) <= max_offset:
                        candidates.append((position, diff, float(t_raw)))
        estimate = _estimate_domain(domain, candidates, tolerance, cfg)
        for evidence_id in members:
            item = next(e for e in evidence if e.evidence_id == evidence_id)
            declared = float(colmap(item.source, item.entry.get("colmap")).get("sigma_s", 60))
            if estimate is None:
                estimates[evidence_id] = ClockEstimate(
                    evidence_id,
                    domain,
                    0.0,
                    declared,
                    0,
                    "declared",
                    "No anchor events shared with a reference clock; declared time zone kept",
                )
            else:
                estimates[evidence_id] = ClockEstimate(
                    evidence_id=evidence_id,
                    domain=domain,
                    offset_s=estimate["offset"],
                    sigma_s=estimate["sigma"],
                    anchors=estimate["anchors"],
                    method=estimate["method"],
                    note=estimate["note"],
                    timezone_shift=estimate["tz"],
                    drift_per_day_s=estimate["drift"],
                    drift_anchor_t=estimate["anchor_t"],
                )
    return estimates


def _estimate_domain(
    domain: str, candidates: list[tuple[int, float, float]], tolerance: float, cfg: dict[str, Any]
) -> dict[str, Any] | None:
    if not candidates:
        return None
    diffs = np.array([c[1] for c in candidates])
    center = _vote(diffs, tolerance)
    best: dict[int, tuple[float, float]] = {}
    for position, diff, t_raw in candidates:
        close = abs(diff - center) <= tolerance
        if close and (position not in best or abs(diff - center) < abs(best[position][0] - center)):
            best[position] = (diff, t_raw)
    matched = np.array([v[0] for v in best.values()])
    times = np.array([v[1] for v in best.values()])
    if len(matched) >= int(cfg["min_anchors"]):
        offset, sigma = _robust(matched)
        keep = np.abs(matched - offset) <= max(3 * sigma, 5.0)
        matched, times = matched[keep], times[keep]
        offset, sigma = _robust(matched)
        drift = 0.0
        anchor_t = float(np.median(times)) if len(times) else 0.0
        span_days = (times.max() - times.min()) / 86400.0 if len(times) else 0.0
        if span_days >= float(cfg["drift_min_span_days"]) and len(matched) >= 6:
            slope, intercept, _, _ = theilslopes(matched, times)
            if abs(slope) * span_days * 86400.0 > 3 * sigma + 30:
                drift = float(slope * 86400.0)
                offset = float(intercept + slope * anchor_t)
        tz = _timezone_shift(offset, float(cfg["timezone_snap_s"]))
        per_record = math.sqrt(sigma**2 + (1.25 * sigma / math.sqrt(len(matched))) ** 2)
        if tz:
            note = (
                f"Records were written in a different time zone: shifted by {describe_duration(offset)} "
                f"using {len(matched)} events also seen in reference records"
            )
        elif abs(offset) > 3 * per_record:
            note = (
                f"Device clock off by {describe_duration(-offset)}; corrected by {describe_duration(offset)} "
                f"using {len(matched)} events also seen in reference records"
            )
        else:
            note = f"Clock agrees with reference records within {per_record:.0f} s ({len(matched)} shared events)"
        return {
            "offset": offset,
            "sigma": per_record,
            "anchors": len(matched),
            "method": "anchor_vote",
            "note": note,
            "tz": tz,
            "drift": drift,
            "anchor_t": anchor_t,
        }
    if len(matched) == 2 and abs(matched[0] - matched[1]) <= 120:
        offset = float(np.mean(matched))
        tz = _timezone_shift(offset, float(cfg["timezone_snap_s"]))
        return {
            "offset": offset,
            "sigma": max(60.0, abs(matched[0] - matched[1])),
            "anchors": 2,
            "method": "anchor_pair",
            "note": f"Corrected by {describe_duration(offset)} from two shared events; wider uncertainty kept",
            "tz": tz,
            "drift": 0.0,
            "anchor_t": 0.0,
        }
    return None


def apply_offsets(obs: pd.DataFrame, estimates: dict[str, ClockEstimate]) -> pd.DataFrame:
    if obs.empty:
        return obs
    offsets = obs["evidence_id"].map(lambda e: estimates[e].offset_s if e in estimates else 0.0)
    drift = obs["evidence_id"].map(lambda e: estimates[e].drift_per_day_s if e in estimates else 0.0)
    anchor = obs["evidence_id"].map(lambda e: estimates[e].drift_anchor_t if e in estimates else 0.0)
    sigma = obs["evidence_id"].map(lambda e: estimates[e].sigma_s if e in estimates else 60.0)
    obs = obs.copy()
    obs["t"] = obs["t_raw"] + offsets + drift * (obs["t_raw"] - anchor) / 86400.0
    obs["sigma_t"] = np.maximum(obs["sigma_t"].fillna(60.0), sigma)
    calibrated = obs["evidence_id"].map(
        lambda e: e in estimates and estimates[e].method in {"anchor_vote", "anchor_pair", "reference"}
    )
    obs.loc[calibrated, "sigma_t"] = sigma[calibrated]
    return obs
