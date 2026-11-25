from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from sakshya.normalise.facts import Facts

DAY = 86400.0


@dataclass
class Transfer:
    key: str
    t: float
    src: str | None
    dst: str | None
    amount: float
    channel: str
    kind: str
    obs_ids: list[str] = field(default_factory=list)
    atm: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "t": self.t,
            "src": self.src,
            "dst": self.dst,
            "amount": self.amount,
            "channel": self.channel,
            "kind": self.kind,
            "obs_ids": self.obs_ids,
            "atm": self.atm,
        }


@dataclass
class Statement:
    account: str
    evidence_id: str
    rows: list[tuple[float, str, float, float | None]]
    opening: float
    start: float
    end: float


def build_transfers(obs: pd.DataFrame, facts: Facts) -> tuple[list[Transfer], dict[str, Statement]]:
    rows = obs[(obs["source"] == "bank_statement") & obs["kind"].isin(["txn", "atm_withdrawal"]) & obs["t"].notna()]
    merged: dict[str, Transfer] = {}
    statements: dict[str, list[tuple[float, str, float, float | None, str]]] = defaultdict(list)
    for row in rows.itertuples(index=False):
        roles = facts.roles.get(row.obs_id, {})
        holder = (roles.get("holder") or [None])[0]
        if holder is None or pd.isna(row.amount):
            continue
        amount = float(row.amount)
        balance = row.attrs.get("balance")
        statements[holder].append((float(row.t), row.direction, amount, balance, row.evidence_id))
        if row.kind == "atm_withdrawal":
            atm = (roles.get("atm") or [None])[0]
            key = f"cash:{row.obs_id}"
            merged[key] = Transfer(
                key, float(row.t), holder, f"cash:{atm}" if atm else "cash", amount, "ATM", "cash", [row.obs_id], atm
            )
            continue
        cps = roles.get("counterparty", [])
        cp_account = next((e for e in cps if e.startswith("account:")), None)
        cp_upi = next((e for e in cps if e.startswith("upi:")), None)
        counterparty = cp_account or (facts.upi_account.get(cp_upi) if cp_upi else None) or cp_upi
        ref = row.attrs.get("ref") or ""
        if counterparty is None:
            kind = "external_out" if row.direction == "DR" else "external_in"
            key = f"ext:{row.obs_id}"
            src, dst = (holder, None) if row.direction == "DR" else (None, holder)
            merged[key] = Transfer(key, float(row.t), src, dst, amount, row.attrs.get("channel", ""), kind, [row.obs_id])
            continue
        src, dst = (holder, counterparty) if row.direction == "DR" else (counterparty, holder)
        key = f"ref:{ref}:{src}:{dst}" if ref else f"obs:{row.obs_id}"
        if key in merged:
            merged[key].obs_ids.append(row.obs_id)
            merged[key].t = min(merged[key].t, float(row.t))
        else:
            merged[key] = Transfer(key, float(row.t), src, dst, amount, row.attrs.get("channel", ""), "transfer", [row.obs_id])
    books: dict[str, Statement] = {}
    for account, entries in statements.items():
        entries.sort(key=lambda e: e[0])
        first = entries[0]
        signed = first[2] if first[1] == "CR" else -first[2]
        opening = (first[3] - signed) if first[3] is not None else 0.0
        books[account] = Statement(
            account, first[4], [(e[0], e[1], e[2], e[3]) for e in entries], opening, entries[0][0], entries[-1][0]
        )
    ordered = sorted(merged.values(), key=lambda tr: (tr.t, 0 if tr.kind in {"transfer", "external_in"} else 1, tr.key))
    return ordered, books


@dataclass
class AccountTaint:
    account: str
    hop: int
    statement: bool
    tainted_in: float = 0.0
    tainted_out: float = 0.0
    tainted_cash: float = 0.0
    tainted_held: float = 0.0
    first_t: float | None = None
    last_out_t: float | None = None
    balance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class TaintResult:
    policy: str
    as_of: float | None
    seed_accounts: list[str]
    victim_out: float
    accounts: dict[str, AccountTaint]
    flows: list[dict[str, Any]]
    origin_keys: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "as_of": self.as_of,
            "seed_accounts": self.seed_accounts,
            "victim_out": self.victim_out,
            "accounts": [a.to_dict() for a in sorted(self.accounts.values(), key=lambda a: (a.hop, -a.tainted_in))],
            "flows": self.flows,
            "origin_keys": self.origin_keys,
        }


def suspicious_payments(
    transfers: list[Transfer], seed_accounts: list[str], new_payee_days: float, reference_t: float | None
) -> list[Transfer]:
    first_paid: dict[str, float] = {}
    for tr in transfers:
        if tr.src in seed_accounts and tr.kind == "transfer" and tr.dst:
            first_paid.setdefault(tr.dst, tr.t)
    horizon = (reference_t if reference_t is not None else max((tr.t for tr in transfers), default=0.0)) - new_payee_days * DAY
    return [
        tr
        for tr in transfers
        if tr.src in seed_accounts and tr.kind == "transfer" and tr.dst and tr.amount >= 1000 and first_paid[tr.dst] >= horizon
    ]


def trace(
    transfers: list[Transfer],
    books: dict[str, Statement],
    seed_accounts: list[str],
    policy: str = "pro_rata",
    as_of: float | None = None,
    new_payee_days: float = 30.0,
    reference_t: float | None = None,
) -> TaintResult:
    origins = {tr.key for tr in suspicious_payments(transfers, seed_accounts, new_payee_days, reference_t)}
    balance: dict[str, float] = {acct: book.opening for acct, book in books.items()}
    tainted: dict[str, float] = defaultdict(float)
    lots: dict[str, deque] = {acct: deque([[max(book.opening, 0.0), 0.0]]) for acct, book in books.items()}
    accounts: dict[str, AccountTaint] = {}
    flows: list[dict[str, Any]] = []
    victim_out = 0.0
    for tr in transfers:
        if as_of is not None and tr.t > as_of:
            break
        carried = 0.0
        if tr.key in origins:
            carried = tr.amount
            victim_out += tr.amount
        elif tr.src and tainted.get(tr.src, 0.0) > 0.005:
            if policy == "fifo":
                carried = _fifo_take(lots.setdefault(tr.src, deque()), tr.amount)
            else:
                before = balance.get(tr.src, tainted[tr.src])
                share = min(1.0, tainted[tr.src] / max(before, tr.amount, 1e-9))
                carried = min(tainted[tr.src], tr.amount * share)
                if tr.src in lots:
                    _fifo_take(lots[tr.src], tr.amount)
            tainted[tr.src] -= carried
            info = accounts.get(tr.src)
            if info is not None:
                info.tainted_out += carried if tr.kind != "cash" else 0.0
                info.tainted_cash += carried if tr.kind == "cash" else 0.0
                info.last_out_t = tr.t
        elif tr.src in lots:
            _fifo_take(lots[tr.src], tr.amount)
        if tr.src in balance:
            balance[tr.src] -= tr.amount
        if tr.dst and not tr.dst.startswith("cash"):
            balance[tr.dst] = balance.get(tr.dst, 0.0) + tr.amount
            lots.setdefault(tr.dst, deque()).append([tr.amount, carried])
            if carried > 0.005:
                tainted[tr.dst] += carried
                src_hop = accounts[tr.src].hop if tr.src in accounts else 0
                info = accounts.get(tr.dst)
                if info is None:
                    info = accounts[tr.dst] = AccountTaint(tr.dst, src_hop + 1, tr.dst in books, first_t=tr.t)
                info.tainted_in += carried
        if carried > 0.005:
            flows.append(
                {
                    "key": tr.key,
                    "t": tr.t,
                    "src": tr.src,
                    "dst": tr.dst,
                    "amount": tr.amount,
                    "tainted": round(carried, 2),
                    "kind": tr.kind,
                    "obs_ids": tr.obs_ids,
                    "atm": tr.atm,
                    "origin": tr.key in origins,
                }
            )
    for account, info in accounts.items():
        info.tainted_held = max(0.0, round(tainted.get(account, 0.0), 2))
        info.balance = round(balance.get(account, 0.0), 2) if account in books else None
    return TaintResult(policy, as_of, list(seed_accounts), round(victim_out, 2), accounts, flows, sorted(origins))


def _fifo_take(queue: deque, amount: float) -> float:
    remaining = amount
    carried = 0.0
    while remaining > 1e-9 and queue:
        lot = queue[0]
        take = min(lot[0], remaining)
        fraction = (lot[1] / lot[0]) if lot[0] > 0 else 0.0
        carried += take * fraction
        lot[1] -= take * fraction
        lot[0] -= take
        remaining -= take
        if lot[0] <= 1e-9:
            queue.popleft()
    return carried
