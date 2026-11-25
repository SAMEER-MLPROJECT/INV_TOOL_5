from __future__ import annotations

from typing import Any

from sakshya.core.identifiers import display
from sakshya.money.flows import TaintResult

BASELINE_MOVE = 0.2


def freeze_list(taint: TaintResult, prediction: dict[str, Any], hypothesis: dict[str, Any] | None) -> list[dict[str, Any]]:
    cash_roles: set[str] = set()
    if hypothesis:
        binding = hypothesis.get("binding", {})
        for role in ("mule_l1", "mule_l2"):
            cash_roles |= set(binding.get(role, []))
    p_cash = prediction.get("p_before_freeze") if prediction.get("next") == "cash_out" else None
    rows = []
    for account in taint.accounts.values():
        if account.tainted_held <= 1:
            continue
        if p_cash is not None and account.account in cash_roles:
            p_move = p_cash
            basis = "predicted cash-out before a freeze can land"
        else:
            p_move = BASELINE_MOVE
            basis = "general chance funds move before a freeze lands"
        expected = account.tainted_held * (1.0 - p_move)
        rows.append(
            {
                "account": account.account,
                "label": display(account.account),
                "hop": account.hop,
                "held": round(account.tainted_held, 2),
                "received": round(account.tainted_in, 2),
                "statement": account.statement,
                "p_move": round(p_move, 3),
                "expected_recoverable": round(expected, 2),
                "basis": basis,
                "action": (
                    "Request immediate debit freeze"
                    if account.statement
                    else "Request statement and debit freeze; no statement in the case yet"
                ),
            }
        )
    rows.sort(key=lambda r: (-r["expected_recoverable"], r["account"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def linked_cases(case_id: str, entities: set[str], index: dict[str, set[str]]) -> list[dict[str, Any]]:
    shared: dict[str, set[str]] = {}
    for entity in entities:
        for other in index.get(entity, set()):
            if other != case_id:
                shared.setdefault(other, set()).add(entity)
    return [{"case_id": other, "shared": sorted(items)} for other, items in sorted(shared.items(), key=lambda kv: -len(kv[1]))]
