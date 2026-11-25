from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Any

from scipy.stats import kendalltau

from sakshya.core.hashing import load_json
from sakshya.pipeline import Analysis, bundle

CRIME_CLASSES = {"upi_investment_fraud", "sextortion", "sim_swap_takeover"}


def _obs_key(analysis: Analysis, obs_id: str) -> tuple[str, int] | None:
    if obs_id not in analysis.obs.index:
        return None
    row = analysis.obs.loc[obs_id]
    return row["file"], int(row["row"])


def _ref(value: list) -> tuple[str, int]:
    return value[0], int(value[1])


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        (2 * precision * recall / (precision + recall))
        if precision and recall
        else (0.0 if precision == 0 or recall == 0 else None)
    )
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def extraction(analysis: Analysis) -> dict[str, Any]:
    per_source: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "parsed": 0})
    counts = analysis.obs.groupby("evidence_id").size().to_dict()
    for item in analysis.evidence:
        if item.source in {"media", "tower_list"}:
            continue
        path = analysis.case_dir / item.file
        if item.file.endswith(".csv"):
            rows = max(0, len([l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]) - 1)
        elif item.source == "chat":
            rows = sum(1 for l in path.read_text(encoding="utf-8").splitlines() if " - " in l[:30])
        elif item.source == "cloud_location":
            rows = len(load_json(path).get("locations", [])) + 1
        elif item.source == "uniaethel":
            rows = len(load_json(path).get("incidents", []))
        else:
            rows = 1
        per_source[item.source]["rows"] += rows
        per_source[item.source]["parsed"] += int(counts.get(item.evidence_id, 0))
    out = {}
    for source, data in per_source.items():
        out[source] = {**data, "coverage": min(1.0, data["parsed"] / data["rows"]) if data["rows"] else None}
    return out


def clock_errors(analysis: Analysis, truth: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    by_file = {e.file: e for e in analysis.evidence}
    for file, spec in truth.get("clock", {}).items():
        item = by_file.get(file)
        if item is None:
            continue
        estimate = analysis.clocks[item.evidence_id]
        results.append(
            {
                "file": file,
                "truth_s": spec["offset_s"],
                "estimate_s": round(estimate.offset_s, 1),
                "error_s": round(abs(estimate.offset_s - spec["offset_s"]), 1),
                "kind": spec["kind"],
                "detected_timezone": estimate.timezone_shift,
                "method": estimate.method,
            }
        )
    return results


def _groups(pairs: set[frozenset]) -> dict[Any, int]:
    parent: dict[Any, Any] = {}

    def find(x: Any) -> Any:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        a, b = tuple(pair)
        parent[find(a)] = find(b)
    roots: dict[Any, int] = {}
    return {node: roots.setdefault(find(node), len(roots)) for node in list(parent)}


def same_event_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    parsed = {(_obs_key(analysis, o)) for o in analysis.obs.index}
    truth_pairs = {frozenset({_ref(a), _ref(b)}) for a, b in truth.get("same_event", [])}
    truth_pairs = {p for p in truth_pairs if all(k in parsed for k in p)}
    found = set()
    for link in analysis.links:
        if link.type == "same_event" and link.status in {"inferred", "confirmed"}:
            a, b = _obs_key(analysis, link.a), _obs_key(analysis, link.b)
            if a and b:
                found.add(frozenset({a, b}))
    truth_group = _groups(truth_pairs)
    found_group = _groups(found)
    tp = sum(1 for p in found if len({truth_group.get(k, ("x", k)) for k in p}) == 1 and all(k in truth_group for k in p))
    recalled = sum(1 for p in truth_pairs if all(k in found_group for k in p) and len({found_group[k] for k in p}) == 1)
    scores = _prf(tp, len(found) - tp, len(truth_pairs) - recalled)
    scores["recall"] = recalled / len(truth_pairs) if truth_pairs else None
    return scores


def presence_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    cash_person = set()
    cash_key = truth.get("roles", {}).get("cashout")
    if cash_key:
        cash_person = set(truth["persons"].get(cash_key, []))
    truth_entities = {c["entity"] for c in truth.get("co_presence", [])}
    inferred = [l for l in analysis.links if l.type == "co_presence" and l.status in {"inferred", "confirmed"}]
    tp_links = sum(1 for l in inferred if l.a in cash_person or l.a in truth_entities)
    found_entities = {l.a for l in inferred}
    impossible_truth = {c["entity"] for c in truth.get("impossible", [])}
    impossible_found = {l.a for l in analysis.links if l.type == "impossibility"}
    return {
        "links": _prf(tp_links, len(inferred) - tp_links, 0)["precision"],
        "entity_recall": (len(found_entities & truth_entities) / len(truth_entities)) if truth_entities else None,
        "impossibility_recall": (len(impossible_found & impossible_truth) / len(impossible_truth)) if impossible_truth else None,
        "posteriors": [round(l.posterior, 4) for l in inferred if l.a in truth_entities and l.posterior is not None],
    }


def resolution_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    present = set(analysis.view.entity_person)
    owner = {}
    for key, members in truth.get("persons", {}).items():
        for member in members:
            if member in present:
                owner[member] = key
    entities = sorted(owner)
    tp = fp = fn = 0
    for a, b in combinations(entities, 2):
        same_truth = owner[a] == owner[b]
        same_engine = analysis.view.entity_person[a] == analysis.view.entity_person[b]
        if same_truth and same_engine:
            tp += 1
        elif same_engine:
            fp += 1
        elif same_truth:
            fn += 1
    decoys = 0
    for a, b in truth.get("decoy_pairs", []):
        if a in present and b in present and analysis.view.entity_person[a] == analysis.view.entity_person[b]:
            decoys += 1
    return {**_prf(tp, fp, fn), "decoy_merges": decoys, "decoy_pairs": len(truth.get("decoy_pairs", []))}


def timeline_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    lookup = {(_obs_key(analysis, o)): o for o in analysis.obs.index}
    truth_t, raw_t, fixed_t = [], [], []
    errors = []
    for event in truth.get("events", []):
        ref = event.get("ref")
        if not ref:
            continue
        obs_id = lookup.get(_ref(ref))
        if obs_id is None:
            continue
        row = analysis.obs.loc[obs_id]
        truth_t.append(event["time"])
        raw_t.append(float(row["t_raw"]))
        fixed_t.append(float(row["t"]))
        errors.append(abs(float(row["t"]) - event["time"]))
    for file, spec in truth.get("clock", {}).items():
        item = next((e for e in analysis.evidence if e.file == file), None)
        if item is None:
            continue
        rows = analysis.obs[analysis.obs["evidence_id"] == item.evidence_id]
        for t_raw, t in zip(rows["t_raw"].head(200), rows["t"].head(200)):
            true_time = float(t_raw) + spec["offset_s"]
            truth_t.append(true_time)
            raw_t.append(float(t_raw))
            fixed_t.append(float(t))
            errors.append(abs(float(t) - true_time))
    if len(truth_t) < 3:
        return {"events": len(truth_t)}
    before = kendalltau(truth_t, raw_t).statistic
    after = kendalltau(truth_t, fixed_t).statistic
    errors.sort()
    return {
        "events": len(truth_t),
        "kendall_tau_before": round(float(before), 4),
        "kendall_tau_after": round(float(after), 4),
        "median_error_s": round(errors[len(errors) // 2], 1),
        "p90_error_s": round(errors[int(len(errors) * 0.9)], 1),
    }


def money_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    money = truth.get("money", {})
    truth_set = set(money.get("tainted_accounts", []))
    found = {a for a, info in analysis.taint.accounts.items() if info.tainted_in > 0}
    tp = len(found & truth_set)
    scores = _prf(tp, len(found - truth_set), len(truth_set - found))
    cash_truth = money.get("cash_withdrawn", 0.0)
    cash_found = sum(info.tainted_cash for info in analysis.taint.accounts.values())
    scores["victim_total_truth"] = money.get("victim_total", 0.0)
    scores["victim_total_found"] = analysis.taint.victim_out
    scores["cash_truth"] = cash_truth
    scores["cash_found"] = round(cash_found, 2)
    scores["cash_error_share"] = round(abs(cash_found - cash_truth) / cash_truth, 4) if cash_truth else None
    return scores


def role_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    decision = analysis.explained["decision"]
    crime = analysis.crime_hypothesis()
    out: dict[str, Any] = {
        "class_truth": truth["class"],
        "class_found": decision["label"],
        "class_correct": decision["label"] == truth["class"],
    }
    if truth["class"] not in CRIME_CLASSES or crime is None:
        return out
    binding = crime.get("binding", {})
    truth_mule = {m for key in truth["roles"].get("mule_l1", []) for m in truth["persons"][key] if m.startswith("account:")}
    found_mule = set(binding.get("mule_l1", []))
    out["mule_l1_correct"] = bool(truth_mule) and truth_mule == found_mule
    cash_key = truth["roles"].get("cashout")
    if cash_key:
        cash_ids = set(truth["persons"][cash_key])
        units = binding.get("cashout", [])
        members = set().union(*(analysis.view.members(u) for u in units)) if units else set()
        out["cashout_correct"] = bool(members & cash_ids)
    variant = truth.get("variants", {}).get("mule_l1")
    if variant:
        out["variant_correct"] = crime.get("variant", {}).get("mule_l1") == variant
    return out


def traceability(analysis: Analysis, data: dict[str, Any]) -> dict[str, Any]:
    refs = set()
    for hypothesis in analysis.explained["hypotheses"]:
        for phase in hypothesis.get("phases", []):
            refs |= set(phase.get("events", []))
        for item in hypothesis.get("breakdown", []):
            refs |= set(item.get("evidence", []) or [])
    for link in analysis.links:
        if link.status in {"inferred", "confirmed"}:
            refs |= set(link.basis)
    refs = {r for r in refs if r}
    hashes = {e.evidence_id: e.sha256 for e in analysis.evidence}
    resolvable = sum(1 for r in refs if r in analysis.obs.index and hashes.get(analysis.obs.at[r, "evidence_id"]))
    return {"pointers": len(refs), "resolvable": resolvable, "share": resolvable / len(refs) if refs else 1.0}


def tamper_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any]:
    flagged = {m["file"] for m in analysis.media if m["status"] == "mismatch"}
    expected = set(truth.get("tampered", []))
    return {"expected": len(expected), "caught": len(flagged & expected), "false_alarms": len(flagged - expected)}


def prediction_scores(analysis: Analysis, truth: dict[str, Any]) -> dict[str, Any] | None:
    money = truth.get("money", {})
    if truth["class"] not in CRIME_CLASSES or not money.get("layering_time") or not money.get("first_cash_time"):
        return None
    as_of = money["layering_time"] + 600
    result = analysis.predict(as_of)
    if not result.get("available"):
        return {"available": False}
    actual = (money["first_cash_time"] - as_of) / 60.0
    return {
        "available": True,
        "phase": result.get("current"),
        "next": result.get("next"),
        "phase_correct": result.get("current") == "layering" and result.get("next") == "cash_out",
        "predicted_median_min": result.get("median_remaining_min"),
        "actual_min": round(actual, 1),
        "error_min": round(abs(result.get("median_remaining_min", 0) - actual), 1)
        if result.get("median_remaining_min") is not None
        else None,
    }


def calibration_rows(analysis: Analysis, truth: dict[str, Any]) -> list[tuple[str, float, bool, float | None]]:
    rows = []
    truth_pairs = {frozenset({_ref(a), _ref(b)}) for a, b in truth.get("same_event", [])}
    owner = {m: k for k, members in truth.get("persons", {}).items() for m in members}
    cash_key = truth.get("roles", {}).get("cashout")
    cash_ids = set(truth["persons"].get(cash_key, [])) if cash_key else set()
    truth_group = _groups(truth_pairs)
    for link in analysis.links:
        if link.status in {"observed", "rejected"}:
            continue
        if link.type == "same_event":
            a, b = _obs_key(analysis, link.a), _obs_key(analysis, link.b)
            same = a in truth_group and b in truth_group and truth_group[a] == truth_group[b]
            rows.append(("same_event", link.w, same, None))
        elif link.type == "same_actor" and link.a in owner and link.b in owner:
            rows.append(("same_actor", link.w, owner[link.a] == owner[link.b], None))
    if cash_ids:
        for item in analysis.presence_scored:
            rows.append(("co_presence", item["w"], item["entity"] in cash_ids, item["prior_odds"]))
    return rows


def evaluate_case(analysis: Analysis) -> dict[str, Any]:
    truth = load_json(analysis.case_dir / "truth.json")
    data = bundle(analysis)
    return {
        "case_id": analysis.case_id,
        "class": truth["class"],
        "extraction": extraction(analysis),
        "clock": clock_errors(analysis, truth),
        "same_event": same_event_scores(analysis, truth),
        "presence": presence_scores(analysis, truth),
        "resolution": resolution_scores(analysis, truth),
        "timeline": timeline_scores(analysis, truth),
        "money": money_scores(analysis, truth),
        "roles": role_scores(analysis, truth),
        "traceability": traceability(analysis, data),
        "tamper": tamper_scores(analysis, truth),
        "prediction": prediction_scores(analysis, truth),
        "digest": data["digest"],
        "timings": data["timings"],
        "_calibration": calibration_rows(analysis, truth),
    }


def summarise_bands(rows: list[tuple[str, float, bool, float | None]]) -> list[dict[str, Any]]:
    bands = [
        (-math.inf, 0, "W below 0"),
        (0, 1, "W 0 to 1"),
        (1, 2, "W 1 to 2"),
        (2, 3, "W 2 to 3"),
        (3, 4, "W 3 to 4"),
        (4, math.inf, "W 4 and above"),
    ]
    out = []
    for low, high, label in bands:
        members = [r for r in rows if low <= r[1] < high]
        if not members:
            continue
        out.append(
            {
                "band": label,
                "links": len(members),
                "true_share": round(sum(1 for r in members if r[2]) / len(members), 4),
                "by_type": {t: sum(1 for r in members if r[0] == t) for t in sorted({r[0] for r in members})},
            }
        )
    return out
