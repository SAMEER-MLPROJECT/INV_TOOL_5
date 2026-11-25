from __future__ import annotations

import math
from typing import Any

from sakshya.core.config import settings
from sakshya.core.identifiers import display

TEMPER = 3.0
ROLE_WORDS = {
    "lurer": "lurer",
    "extortionist": "extortionist",
    "cashout": "cash-out agent",
    "swapper": "SIM swapper",
    "controller": "controller",
}


def _entropy(probabilities: list[float]) -> float:
    return -sum(p * math.log2(p) for p in probabilities if p > 0)


def _posterior(hypotheses: list[dict[str, Any]]) -> list[float]:
    top = max(h["score"] for h in hypotheses)
    weights = [10 ** max((h["score"] - top) / TEMPER, -12) for h in hypotheses]
    total = sum(weights)
    return [w / total for w in weights]


def _bound(hypothesis: dict[str, Any], targets: set[str], roles: set[str] | None) -> bool:
    for role, units in hypothesis.get("binding", {}).items():
        if roles and role not in roles:
            continue
        if set(units) & targets:
            return True
    return False


def _eig(hypotheses: list[dict[str, Any]], prior: list[float], likelihood: list[float]) -> float:
    p_yes = sum(p * l for p, l in zip(prior, likelihood))
    p_no = 1.0 - p_yes
    after_yes = [p * l / p_yes for p, l in zip(prior, likelihood)] if p_yes > 0 else prior
    after_no = [p * (1 - l) / p_no for p, l in zip(prior, likelihood)] if p_no > 0 else prior
    return max(0.0, _entropy(prior) - (p_yes * _entropy(after_yes) + p_no * _entropy(after_no)))


def candidate_requests(case: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    sources = case["sources"]
    statements = case["statement_accounts"]
    cdr_phones = case["cdr_phones"]
    for account in case["tainted_accounts"]:
        if account not in statements:
            requests.append(
                {
                    "kind": "account_statement",
                    "title": f"Statement, KYC and freeze for {display(account)}",
                    "days": 2,
                    "targets": {account},
                    "roles": {"mule_l1", "mule_l2"},
                    "phase": "cash_out",
                    "why": "Traced money reached this account but its onward movement is not in the case",
                }
            )
    for hypothesis in case["hypotheses"][:3]:
        binding = hypothesis.get("binding", {})
        for role in ("lurer", "extortionist", "cashout", "swapper", "controller"):
            for unit in binding.get(role, []):
                for phone in case["person_phones"].get(unit, []):
                    if phone not in cdr_phones:
                        requests.append(
                            {
                                "kind": "cdr",
                                "title": f"CDR, tower data and subscriber details for {display(phone)}",
                                "days": 3,
                                "targets": {unit},
                                "roles": {role},
                                "phase": "contact",
                                "why": (
                                    f"Would be the {ROLE_WORDS[role]} if the case is {hypothesis['label'].lower()}; "
                                    "this number has no call records in the case"
                                ),
                            }
                        )
        for unit in binding.get("mule_l1", []):
            requests.append(
                {
                    "kind": "interview",
                    "title": f"Record a statement from the holder of {display(unit)}",
                    "days": 1,
                    "targets": {unit},
                    "roles": {"mule_l1"},
                    "phase": "layering",
                    "variant": "knowing",
                    "why": "Separates a knowing mule from an unwitting account holder",
                }
            )
    for atm in case["cash_atms"]:
        if atm not in case["cctv_atms"]:
            requests.append(
                {
                    "kind": "cctv",
                    "title": f"CCTV footage from {display(atm)} for the withdrawal times",
                    "days": 2,
                    "targets": {atm},
                    "roles": {"cashout"},
                    "phase": "cash_out",
                    "why": "Cash was withdrawn here but no camera record is in the case",
                }
            )
        if atm not in case["dump_atms"]:
            requests.append(
                {
                    "kind": "tower_dump",
                    "title": f"Tower dump for cells around {display(atm)}",
                    "days": 3,
                    "targets": {atm},
                    "roles": {"cashout"},
                    "phase": "cash_out",
                    "why": "Would show which phones were present at the withdrawal",
                }
            )
    for target in case["infrastructure"]:
        requests.append(
            {
                "kind": "hosting",
                "title": f"Hosting and registration records for {display(target)}",
                "days": 10,
                "targets": {target},
                "roles": {"controller"},
                "phase": "control",
                "why": "Identifies who rents the infrastructure behind the scam",
            }
        )
    if "bank_statement" not in sources:
        requests.append(
            {
                "kind": "victim_statement",
                "title": "Complainant's bank statement for the complaint period",
                "days": 1,
                "targets": set(),
                "roles": set(),
                "phase": "payment",
                "why": "Payments cannot be traced without it",
            }
        )
    unique = {}
    for request in requests:
        unique.setdefault(request["title"], request)
    return list(unique.values())


def rank_leads(case: dict[str, Any]) -> list[dict[str, Any]]:
    hypotheses = case["hypotheses"][:6]
    if not hypotheses:
        return []
    prior = _posterior(hypotheses)
    top = hypotheses[0]
    weak_roles = {r["name"] for r in top.get("roles", []) if not r["units"]}
    held = case.get("held", {})
    total_held = sum(held.values()) or 1.0
    leads = []
    for request in candidate_requests(case):
        likelihood = []
        for hypothesis in hypotheses:
            if hypothesis["template"] == "no_offence":
                likelihood.append(0.1)
            elif request.get("variant"):
                likelihood.append(0.7 if request["variant"] in " ".join(hypothesis.get("variant", {}).values()) else 0.3)
            elif not request["targets"] or _bound(hypothesis, request["targets"], request["roles"]):
                likelihood.append(0.85)
            else:
                likelihood.append(0.35)
        eig = _eig(hypotheses, prior, likelihood)
        gap = 0.25 if (request["phase"] in top.get("gaps", []) or request["roles"] & weak_roles) else 0.0
        money = 0.3 * sum(held.get(t, 0.0) for t in request["targets"]) / total_held
        value = (eig + gap + money) / request["days"]
        reasons = []
        if eig >= 0.01:
            reasons.append(f"separates the leading explanations ({eig:.2f} bits)")
        if gap:
            reasons.append("fills a gap in the reconstruction")
        if money:
            reasons.append("traced money is still held there")
        leads.append(
            {
                "title": request["title"],
                "kind": request["kind"],
                "days": request["days"],
                "why": request["why"],
                "phase": request["phase"],
                "eig_bits": round(eig, 4),
                "value_per_day": round(value, 4),
                "value_parts": {"information": round(eig, 4), "gap": gap, "money": round(money, 4)},
                "reasons": reasons,
                "targets": sorted(request["targets"]),
            }
        )
    leads.sort(key=lambda lead: (-lead["value_per_day"], lead["days"], lead["title"]))
    limit = settings()["decide"]["max_leads"]
    for rank, lead in enumerate(leads[:limit], start=1):
        lead["rank"] = rank
    return leads[:limit]


def fragility(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    crimes = [h for h in hypotheses if h["template"] != "no_offence"]
    if not crimes:
        return {"available": False}
    top = crimes[0]
    rivals = [h["score"] for h in hypotheses if h["template"] != top["template"]]
    rival = max(rivals) if rivals else 0.0
    if top["score"] <= rival:
        return {"available": False}
    support = sorted(
        [item for item in top["breakdown"] if item["w"] > 0 and item["kind"] in {"indicator", "link"}],
        key=lambda item: -item["w"],
    )
    removed = []
    score = top["score"]
    for item in support:
        if score < rival:
            break
        score -= item["w"]
        removed.append(item)
    return {
        "available": True,
        "hypothesis": top["id"],
        "score": top["score"],
        "rival_score": rival,
        "rests_on": [
            {
                "label": item.get("detail") or item.get("label") or item.get("name"),
                "w": item["w"],
                "name": item.get("name"),
                "link_id": item.get("link_id"),
                "entity": item.get("entity"),
            }
            for item in removed
        ],
        "count": len(removed),
        "robust": len(removed) >= 3,
        "message": _fragility_message(len(removed), score < rival),
    }


def _fragility_message(count: int, falls: bool) -> str:
    if not falls:
        return "The leading explanation stays ahead even without its strongest support items"
    if count == 1:
        return "The leading explanation would fall below the next one if the single strongest piece of support below were removed"
    return f"The leading explanation would fall below the next one if the {count} strongest pieces of support below were removed"
