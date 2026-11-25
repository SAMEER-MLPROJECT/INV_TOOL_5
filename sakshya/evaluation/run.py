from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scipy.optimize import minimize_scalar

from sakshya import __version__
from sakshya.core.config import CONFIG_DIR, reload_calibration
from sakshya.core.hashing import dump_json
from sakshya.evaluation.metrics import evaluate_case, summarise_bands
from sakshya.generator import CaseSpec, generate_case, heldout_specs, training_specs
from sakshya.pipeline import analyse, bundle

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "evaluation" / "results.json"


def _mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return round(statistics.fmean(clean), 4) if clean else None


def fit_scale(rows: list[tuple[str, float, bool, float | None]]) -> dict[str, Any]:
    usable = [(w, y, prior) for kind, w, y, prior in rows if kind == "co_presence" and prior]
    if len(usable) < 5:
        return {"scale": 1.0, "links": len(usable), "note": "Too few labelled presence links to fit"}

    def loss(k: float) -> float:
        total = 0.0
        for w, y, prior in usable:
            logit = k * w * math.log(10) + math.log(prior)
            p = 1 / (1 + math.exp(-max(min(logit, 40), -40)))
            p = min(max(p, 1e-9), 1 - 1e-9)
            total -= math.log(p) if y else math.log(1 - p)
        return total / len(usable)

    result = minimize_scalar(loss, bounds=(0.3, 2.0), method="bounded")
    return {
        "scale": round(float(result.x), 3),
        "links": len(usable),
        "log_loss": round(float(result.fun), 4),
        "log_loss_unscaled": round(loss(1.0), 4),
    }


def run_suite(specs: list[CaseSpec], work: Path) -> list[dict[str, Any]]:
    results = []
    for spec in specs:
        case_dir = generate_case(spec, work)
        started = time.perf_counter()
        analysis = analyse(case_dir, record=False)
        elapsed = time.perf_counter() - started
        result = evaluate_case(analysis)
        result["analysis_s"] = round(elapsed, 3)
        results.append(result)
    return results


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for source, data in r["extraction"].items():
            if data["coverage"] is not None:
                by_source[source].append(data["coverage"])
    clock = [c for r in results for c in r["clock"]]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        confusion[r["roles"]["class_truth"]][r["roles"]["class_found"]] += 1
    crime = [r for r in results if r["roles"].get("mule_l1_correct") is not None]
    predictions = [r["prediction"] for r in results if r.get("prediction") and r["prediction"].get("available")]
    presence_post = [p for r in results for p in r["presence"]["posteriors"]]
    return {
        "cases": len(results),
        "extraction": {s: {"mean_coverage": _mean(v), "files": len(v)} for s, v in sorted(by_source.items())},
        "clock": {
            "files": len(clock),
            "median_error_s": statistics.median([c["error_s"] for c in clock]) if clock else None,
            "max_error_s": max([c["error_s"] for c in clock], default=None),
            "timezone_detected": sum(1 for c in clock if c["kind"] == "timezone" and c["detected_timezone"]),
            "timezone_cases": sum(1 for c in clock if c["kind"] == "timezone"),
        },
        "same_event": {
            "precision": _mean([r["same_event"]["precision"] for r in results]),
            "recall": _mean([r["same_event"]["recall"] for r in results]),
        },
        "presence": {
            "link_precision": _mean([r["presence"]["links"] for r in results]),
            "entity_recall": _mean([r["presence"]["entity_recall"] for r in results]),
            "impossibility_recall": _mean([r["presence"]["impossibility_recall"] for r in results]),
            "median_posterior": statistics.median(presence_post) if presence_post else None,
        },
        "resolution": {
            "precision": _mean([r["resolution"]["precision"] for r in results]),
            "recall": _mean([r["resolution"]["recall"] for r in results]),
            "f1": _mean([r["resolution"]["f1"] for r in results]),
            "decoy_merges": sum(r["resolution"]["decoy_merges"] for r in results),
            "decoy_pairs": sum(r["resolution"]["decoy_pairs"] for r in results),
        },
        "timeline": {
            "kendall_tau_before": _mean([r["timeline"].get("kendall_tau_before") for r in results]),
            "kendall_tau_after": _mean([r["timeline"].get("kendall_tau_after") for r in results]),
            "median_error_s": _mean([r["timeline"].get("median_error_s") for r in results]),
        },
        "money": {
            "precision": _mean([r["money"]["precision"] for r in results]),
            "recall": _mean([r["money"]["recall"] for r in results]),
            "cash_error_share": _mean([r["money"]["cash_error_share"] for r in results]),
        },
        "classification": {
            "accuracy": round(sum(1 for r in results if r["roles"]["class_correct"]) / len(results), 4),
            "confusion": {k: dict(v) for k, v in confusion.items()},
        },
        "roles": {
            "mule_l1_accuracy": _mean([1.0 if r["roles"]["mule_l1_correct"] else 0.0 for r in crime]),
            "cashout_accuracy": _mean(
                [1.0 if r["roles"].get("cashout_correct") else 0.0 for r in crime if "cashout_correct" in r["roles"]]
            ),
            "variant_accuracy": _mean(
                [1.0 if r["roles"].get("variant_correct") else 0.0 for r in crime if "variant_correct" in r["roles"]]
            ),
        },
        "traceability": {
            "share": _mean([r["traceability"]["share"] for r in results]),
            "pointers": sum(r["traceability"]["pointers"] for r in results),
        },
        "tamper": {
            "expected": sum(r["tamper"]["expected"] for r in results),
            "caught": sum(r["tamper"]["caught"] for r in results),
            "false_alarms": sum(r["tamper"]["false_alarms"] for r in results),
        },
        "prediction": {
            "cases": len(predictions),
            "phase_accuracy": _mean([1.0 if p["phase_correct"] else 0.0 for p in predictions]),
            "median_error_min": statistics.median([p["error_min"] for p in predictions if p["error_min"] is not None])
            if predictions
            else None,
        },
        "analysis_time_s": {
            "median": statistics.median([r["analysis_s"] for r in results]),
            "max": max(r["analysis_s"] for r in results),
        },
        "calibration": summarise_bands([row for r in results for row in r["_calibration"]]),
    }


def determinism(work: Path) -> dict[str, Any]:
    case_dir = generate_case(CaseSpec("DET-UPI", "upi_investment_fraud", 7, fixed=True), work)
    first = bundle(analyse(case_dir, record=False))["digest"]
    second = bundle(analyse(case_dir, record=False))["digest"]
    return {"identical": first == second, "digest": first}


def scaling(work: Path, scales: list[float]) -> list[dict[str, Any]]:
    rows = []
    for scale in scales:
        case_dir = generate_case(CaseSpec(f"SCALE-{scale:g}", "upi_investment_fraud", 7, scale=scale, fixed=True), work)
        started = time.perf_counter()
        analysis = analyse(case_dir, record=False)
        data = bundle(analysis)
        rows.append(
            {
                "scale": scale,
                "observations": data["counts"]["observations"],
                "entities": data["counts"]["entities"],
                "seconds": round(time.perf_counter() - started, 3),
                "decision": data["decision"]["label"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the engine on generated cases with answer keys")
    parser.add_argument("--per-kind", type=int, default=6)
    parser.add_argument("--training", type=int, default=8)
    parser.add_argument("--scales", default="1,5,20")
    parser.add_argument("--fit", action="store_true", help="write the fitted calibration scale to the configuration")
    parser.add_argument("--out", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sakshya-eval-") as tmp:
        work = Path(tmp)
        training = run_suite(training_specs(args.training), work / "train")
        calibration = fit_scale([row for r in training for row in r["_calibration"]])
        if args.fit:
            dump_json(
                CONFIG_DIR / "calibration.json",
                {
                    "scales": {"co_presence": calibration["scale"]},
                    "fitted_on": f"{args.training} training cases",
                    "engine": __version__,
                    "log_loss": calibration.get("log_loss"),
                    "log_loss_unscaled": calibration.get("log_loss_unscaled"),
                },
            )
            reload_calibration()
        heldout = run_suite(heldout_specs(args.per_kind), work / "heldout")
        summary = aggregate(heldout)
        payload = {
            "engine": __version__,
            "generated": time.strftime("%Y-%m-%d"),
            "heldout": summary,
            "calibration_fit": calibration,
            "determinism": determinism(work / "det"),
            "scaling": scaling(work / "scale", [float(s) for s in args.scales.split(",")]),
            "cases": [{k: v for k, v in r.items() if k != "_calibration"} for r in heldout],
            "note": (
                "All cases are synthetic and generated with answer keys. The engine never reads the answer keys. "
                "Held-out cases use seeds and structures not used while building the engine."
            ),
        }
    dump_json(args.out, payload)
    print(json.dumps({k: v for k, v in payload.items() if k not in {"cases"}}, indent=2, default=str))


if __name__ == "__main__":
    main()
