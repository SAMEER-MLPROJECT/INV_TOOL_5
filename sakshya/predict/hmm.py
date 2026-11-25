from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import norm

from sakshya.core.config import settings, templates

STAY, ADVANCE, SKIP = 0.55, 0.40, 0.05
HIT, MISS = 0.85, 0.15


def _template(name: str) -> dict[str, Any] | None:
    return next((t for t in templates() if t["class"] == name), None)


def _transition_matrix(size: int) -> np.ndarray:
    matrix = np.zeros((size, size))
    for i in range(size):
        matrix[i, i] = STAY
        if i + 1 < size:
            matrix[i, i + 1] = ADVANCE
        if i + 2 < size:
            matrix[i, i + 2] = SKIP
        matrix[i] /= matrix[i].sum()
    return matrix


def lognormal_cdf(minutes: float, median_min: float, sigma: float) -> float:
    if minutes <= 0:
        return 0.0
    return float(norm.cdf((math.log(minutes) - math.log(median_min)) / sigma))


def predict(hypothesis: dict[str, Any] | None, as_of: float) -> dict[str, Any]:
    cfg = settings()["predict"]
    if not hypothesis or hypothesis.get("template") == "no_offence":
        return {"available": False, "reason": "No offence pattern to track"}
    template = _template(hypothesis["template"])
    if template is None:
        return {"available": False, "reason": "Template not found"}
    phases = [p for p in hypothesis["phases"] if not p.get("optional")]
    names = ["not_started"] + [p["name"] for p in phases]
    labels = ["Not started"] + [p["label"] for p in phases]
    events: list[tuple[float, int]] = []
    for index, phase in enumerate(phases, start=1):
        for t in phase.get("times", []):
            if t <= as_of:
                events.append((t, index))
    events.sort()
    size = len(names)
    belief = np.zeros(size)
    belief[0] = 1.0
    matrix = _transition_matrix(size)
    for _, label in events:
        belief = belief @ matrix
        emission = np.full(size, MISS / max(size - 1, 1))
        emission[label] = HIT
        belief = belief * emission
        belief /= belief.sum()
    current = int(np.argmax(belief))
    posterior = [{"phase": names[i], "label": labels[i], "p": round(float(belief[i]), 4)} for i in range(size)]
    result: dict[str, Any] = {
        "available": True,
        "template": hypothesis["template"],
        "as_of": as_of,
        "posterior": posterior,
        "current": names[current],
        "current_label": labels[current],
        "events_seen": len(events),
    }
    if current == 0 or current >= size - 1:
        result["next"] = None
        result["message"] = (
            "No offence phase observed yet"
            if current == 0
            else f"Final phase ({labels[current]}) reached; nothing further to predict"
        )
        return result
    phase_start = min(t for t, label in events if label == current)
    elapsed_min = max(0.0, (as_of - phase_start) / 60.0)
    spec = template.get("transitions", {}).get(names[current])
    if spec is None:
        result["next"] = None
        result["message"] = "No timing model for this transition"
        return result
    median, sigma = float(spec["median_min"]), float(spec["sigma"])
    done = lognormal_cdf(elapsed_min, median, sigma)
    survival = max(1e-9, 1.0 - done)
    horizons = []
    for horizon in cfg["horizons_min"]:
        p = (lognormal_cdf(elapsed_min + horizon, median, sigma) - done) / survival
        horizons.append({"minutes": horizon, "p": round(min(max(p, 0.0), 1.0), 4)})
    q = done + 0.5 * survival
    remaining = math.exp(math.log(median) + sigma * norm.ppf(min(q, 0.999999))) - elapsed_min
    latency = cfg["freeze_latency_min"]
    within_latency = (lognormal_cdf(elapsed_min + latency, median, sigma) - done) / survival
    result.update(
        {
            "next": names[current + 1],
            "next_label": labels[current + 1],
            "elapsed_min": round(elapsed_min, 1),
            "typical_min": median,
            "horizons": horizons,
            "median_remaining_min": round(max(remaining, 0.0), 1),
            "freeze_latency_min": latency,
            "p_before_freeze": round(min(max(within_latency, 0.0), 1.0), 4),
            "message": (
                f"{labels[current]} started {elapsed_min:.0f} min ago. {labels[current + 1]} usually follows within "
                f"about {median:.0f} min of it; median time left is {max(remaining, 0.0):.0f} min."
            ),
        }
    )
    return result
