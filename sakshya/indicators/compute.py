from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from sakshya.core.config import config_file
from sakshya.core.identifiers import display
from sakshya.model import Link
from sakshya.money.flows import Statement, TaintResult, Transfer
from sakshya.normalise.facts import Facts

DAY = 86400.0


@dataclass
class Indicator:
    name: str
    entity: str
    weight: float
    value: Any
    evidence: list[str]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IndicatorSet:
    def __init__(self) -> None:
        self.by_entity: dict[str, dict[str, Indicator]] = defaultdict(dict)

    def add(self, indicator: Indicator) -> None:
        current = self.by_entity[indicator.entity].get(indicator.name)
        if current is None or abs(indicator.weight) > abs(current.weight):
            self.by_entity[indicator.entity][indicator.name] = indicator

    def of(self, entities: list[str] | set[str]) -> dict[str, Indicator]:
        merged: dict[str, Indicator] = {}
        for entity in sorted(entities):
            for name, indicator in self.by_entity.get(entity, {}).items():
                if name not in merged or abs(indicator.weight) > abs(merged[name].weight):
                    merged[name] = indicator
        return merged

    def all(self) -> list[Indicator]:
        return [i for items in self.by_entity.values() for i in items.values()]


def _keywords(text: str, words: list[str]) -> list[str]:
    lowered = text.lower()
    return sorted({w for w in words if w in lowered})


def compute(
    obs: pd.DataFrame,
    facts: Facts,
    transfers: list[Transfer],
    books: dict[str, Statement],
    taint: TaintResult,
    links: list[Link],
    seeds: list[str],
) -> IndicatorSet:
    cfg = config_file("indicators.yaml")
    w = cfg["weights"]
    result = IndicatorSet()
    _account_indicators(result, cfg, w, obs, facts, transfers, books, taint, seeds)
    _message_indicators(result, cfg, w, obs, facts, seeds)
    _telecom_indicators(result, w, obs, facts, seeds)
    _link_indicators(result, w, links)
    _device_indicators(result, cfg, w, obs, facts)
    return result


def _account_indicators(
    result: IndicatorSet,
    cfg: dict,
    w: dict,
    obs: pd.DataFrame,
    facts: Facts,
    transfers: list[Transfer],
    books: dict[str, Statement],
    taint: TaintResult,
    seeds: list[str],
) -> None:
    window = cfg["pass_through_window_min"] * 60
    split_window = cfg["split_window_min"] * 60
    inflows: dict[str, list[dict]] = defaultdict(list)
    outflows: dict[str, list[dict]] = defaultdict(list)
    for flow in taint.flows:
        if flow["dst"]:
            inflows[flow["dst"]].append(flow)
        if flow["src"]:
            outflows[flow["src"]].append(flow)
    seed_accounts = [s for s in seeds if s.startswith("account:")]
    for account, info in taint.accounts.items():
        ins = inflows.get(account, [])
        outs = outflows.get(account, [])
        origin_ins = [f for f in ins if f["origin"]]
        if origin_ins:
            result.add(
                Indicator(
                    "received_from_victim",
                    account,
                    w["received_from_victim"],
                    sum(f["tainted"] for f in origin_ins),
                    [f["obs_ids"][0] for f in origin_ins],
                    f"Received Rs {sum(f['tainted'] for f in origin_ins):,.0f} directly from the complainant",
                )
            )
        quick = 0.0
        quick_obs = []
        for out in outs:
            if any(0 <= out["t"] - i["t"] <= window for i in ins):
                quick += out["tainted"]
                quick_obs.append(out["obs_ids"][0])
        if info.tainted_in > 0 and outs:
            share = quick / info.tainted_in
            if share >= 0.8:
                result.add(
                    Indicator(
                        "pass_through_fast",
                        account,
                        w["pass_through_fast"],
                        round(share, 3),
                        quick_obs,
                        f"{share:.0%} of the money received was sent on within {window // 60} min",
                    )
                )
            elif share >= 0.5:
                result.add(
                    Indicator(
                        "pass_through_partial",
                        account,
                        w["pass_through_partial"],
                        round(share, 3),
                        quick_obs,
                        f"{share:.0%} of the money received was sent on within {window // 60} min",
                    )
                )
        destinations = {
            o["dst"] for o in outs if o["kind"] != "cash" and ins and any(0 <= o["t"] - i["t"] <= split_window for i in ins)
        }
        if len(destinations) >= 2:
            result.add(
                Indicator(
                    "split_out",
                    account,
                    w["split_out"],
                    len(destinations),
                    [o["obs_ids"][0] for o in outs],
                    f"Split onward to {len(destinations)} accounts within {split_window // 3600} h",
                )
            )
        cash = [o for o in outs if o["kind"] == "cash"]
        if cash:
            result.add(
                Indicator(
                    "cash_withdrawal",
                    account,
                    w["cash_withdrawal"],
                    sum(o["tainted"] for o in cash),
                    [o["obs_ids"][0] for o in cash],
                    f"Rs {sum(o['tainted'] for o in cash):,.0f} of traced money withdrawn in cash",
                )
            )
        opened = _opened(facts, account)
        first = info.first_t
        book = books.get(account)
        if first is not None and (
            (opened is not None and 0 <= first - opened <= cfg["new_account_days"] * DAY)
            or (book is not None and first - book.start <= 30 * DAY and book.start - first < DAY and len(book.rows) <= 12)
        ):
            evidence = facts.entities[account].kyc_obs[:1] if account in facts.entities else []
            result.add(
                Indicator(
                    "new_account",
                    account,
                    w["new_account"],
                    opened,
                    evidence,
                    "Account opened shortly before it received the money",
                )
            )
        if book is not None and info.tainted_in > 0:
            held = info.tainted_held / info.tainted_in
            if held >= cfg["retained_share"]:
                result.add(
                    Indicator(
                        "funds_retained",
                        account,
                        w["funds_retained"],
                        round(held, 3),
                        [],
                        f"Kept {held:.0%} of the money received",
                    )
                )
            elif info.hop == 1 and cfg["commission_band"][0] <= held <= cfg["commission_band"][1]:
                result.add(
                    Indicator(
                        "commission_retained",
                        account,
                        w["commission_retained"],
                        round(held, 4),
                        [],
                        f"Kept {held:.1%} of the money, consistent with a commission",
                    )
                )
    for tr in transfers:
        if tr.src in seed_accounts and tr.dst and tr.kind == "transfer":
            earlier = [o for o in transfers if o.src == tr.src and o.dst == tr.dst and o.t < tr.t - 30 * DAY]
            if earlier:
                result.add(
                    Indicator(
                        "long_history_with_payee",
                        tr.dst,
                        w["long_history_with_payee"],
                        len(earlier),
                        [earlier[0].obs_ids[0]],
                        "Complainant had paid this account more than 30 days earlier",
                    )
                )


def _opened(facts: Facts, account: str) -> float | None:
    info = facts.entities.get(account)
    return info.opened_t if info is not None else None


def _message_indicators(result: IndicatorSet, cfg: dict, w: dict, obs: pd.DataFrame, facts: Facts, seeds: list[str]) -> None:
    messages = obs[obs["kind"].isin(["chat", "email", "sms"])]
    seed_set = set(seeds)
    found: dict[tuple[str, str], tuple[set[str], list[str]]] = defaultdict(lambda: (set(), []))
    for obs_id, row in messages.iterrows():
        senders = [e for e in facts.roles.get(obs_id, {}).get("from", []) if e not in seed_set]
        if not senders:
            continue
        text = f"{row['text']} {row['attrs'].get('subject', '')}"
        for family in ("lure", "threat"):
            hits = _keywords(text, cfg["keywords"][family])
            if hits:
                for sender in senders:
                    words, ids = found[(sender, family)]
                    words.update(hits)
                    ids.append(obs_id)
    for (sender, family), (words, ids) in found.items():
        if len(words) >= 2:
            name = "lure_language" if family == "lure" else "threat_language"
            label = "investment lure" if family == "lure" else "threats or extortion"
            result.add(
                Indicator(
                    name,
                    sender,
                    w[name],
                    sorted(words),
                    ids[:6],
                    f"Messages contain {label} language: {', '.join(sorted(words)[:5])}",
                )
            )


def _telecom_indicators(result: IndicatorSet, w: dict, obs: pd.DataFrame, facts: Facts, seeds: list[str]) -> None:
    for imei, users in facts.handset_users.items():
        if len(users) >= 2:
            evidence = [ids[0] for ids in users.values()]
            result.add(
                Indicator(
                    "many_sims_on_handset",
                    imei,
                    w["many_sims_on_handset"],
                    len(users),
                    evidence,
                    f"{len(users)} SIM cards used in this handset",
                )
            )
    for seed in seeds:
        if not seed.startswith("phone:"):
            continue
        registered = facts.kyc_imsi.get(seed)
        sims = facts.sims_by_phone.get(seed, set())
        if not registered or len(sims) < 2:
            continue
        for sim in sims - {registered}:
            rows = obs[
                (obs["source"] == "cdr")
                & obs["obs_id"].isin(facts.edges[(facts.edges["src"] == seed) & (facts.edges["dst"] == sim)]["obs_id"])
            ]
            rows = rows.sort_values("t")
            if rows.empty:
                continue
            first = rows.iloc[0]
            result.add(
                Indicator(
                    "sim_takeover",
                    sim,
                    w["sim_takeover"],
                    first["t"],
                    [first["obs_id"]],
                    f"A new SIM took over {display(seed)} at {first['place'] or 'an unknown site'}",
                )
            )
            otps = rows[(rows["kind"] == "sms") & (rows["direction"] == "in")]
            if not otps.empty:
                result.add(
                    Indicator(
                        "otp_on_new_sim",
                        sim,
                        w["otp_on_new_sim"],
                        len(otps),
                        otps["obs_id"].tolist()[:4],
                        f"{len(otps)} bank messages delivered to the new SIM",
                    )
                )


def _link_indicators(result: IndicatorSet, w: dict, links: list[Link]) -> None:
    for link in links:
        if link.type == "co_presence" and link.status in {"inferred", "confirmed"}:
            result.add(Indicator("atm_copresence", link.a, w["atm_copresence"], round(link.w, 2), link.basis, link.claim))
        elif link.type == "impossibility" and link.status in {"inferred", "confirmed"}:
            result.add(
                Indicator(
                    "cleared_at_cash",
                    link.a,
                    w["cleared_at_cash"],
                    round(link.extra.get("distance_m", 0) / 1000, 1),
                    link.basis,
                    link.claim,
                )
            )
        elif link.type == "sequence" and link.a_kind == "entity" and link.extra.get("p", 0) >= 0.5:
            result.add(
                Indicator(
                    "contact_before_payment", link.a, w["contact_before_payment"], link.extra.get("p"), link.basis, link.claim
                )
            )
        elif (
            link.type == "same_actor" and link.extra.get("basis") == "infrastructure" and link.status in {"inferred", "confirmed"}
        ):
            result.add(Indicator("infra_overlap", link.a, w["infra_overlap"], link.extra.get("domain"), link.basis, link.claim))


def _device_indicators(result: IndicatorSet, cfg: dict, w: dict, obs: pd.DataFrame, facts: Facts) -> None:
    flows = obs[obs["kind"] == "net_flow"]
    if not flows.empty:
        macs, dsts = [], []
        for obs_id in flows["obs_id"]:
            roles = facts.roles.get(obs_id, {})
            macs.append((roles.get("device") or [None])[0])
            dsts.append((roles.get("dst") or [None])[0])
        frame = flows.assign(mac=macs, dst=dsts)
        frame["bytes_out"] = frame["attrs"].map(lambda a: a.get("bytes_out", 0))
        for (mac, dst), group in frame.groupby(["mac", "dst"]):
            if mac is None or dst is None:
                continue
            times = np.sort(group["t"].to_numpy())
            if len(times) >= cfg["beaconing"]["min_flows"]:
                gaps = np.diff(times)
                median = float(np.median(gaps))
                regular = gaps[gaps <= 5 * median]
                cv = float(np.std(regular) / np.mean(regular)) if len(regular) > 5 and np.mean(regular) > 0 else 1.0
                if cv <= cfg["beaconing"]["max_cv"]:
                    result.add(
                        Indicator(
                            "beaconing",
                            mac,
                            w["beaconing"],
                            round(median),
                            group["obs_id"].tolist()[:3],
                            f"Contacted {display(dst)} every {median / 60:.1f} min ({len(times)} times, "
                            f"variation {cv:.0%}), typical of command-and-control check-ins",
                        )
                    )
            total = int(group["bytes_out"].sum())
            if total >= cfg["exfil"]["min_bytes"]:
                result.add(
                    Indicator(
                        "exfil_volume",
                        mac,
                        w["exfil_volume"],
                        total,
                        group["obs_id"].tolist()[:3],
                        f"Sent {total / 1e6:,.0f} MB to {display(dst)}",
                    )
                )
    incidents = obs[obs["kind"] == "net_incident"]
    for obs_id, row in incidents.iterrows():
        hosts = facts.roles.get(obs_id, {}).get("host", [])
        for host in hosts:
            mac = facts.lan_ip_mac.get(host, host)
            label = str(row["attrs"].get("label", "")).upper()
            if label == "C2":
                result.add(
                    Indicator(
                        "beaconing",
                        mac,
                        w["beaconing"],
                        label,
                        [obs_id],
                        f"Network analysis flagged C2-like beaconing from {display(host)}",
                    )
                )
            elif label == "EXFIL":
                result.add(
                    Indicator(
                        "exfil_volume",
                        mac,
                        w["exfil_volume"],
                        label,
                        [obs_id],
                        f"Network analysis flagged data exfiltration from {display(host)}",
                    )
                )


def attach_kyc_dates(facts: Facts, obs: pd.DataFrame) -> None:
    kyc = obs[obs["kind"] == "kyc"]
    for obs_id, row in kyc.iterrows():
        stamp = row["attrs"].get("opened_on") or row["attrs"].get("activated_on")
        if not stamp:
            continue
        try:
            value = datetime.fromisoformat(str(stamp)).timestamp()
        except ValueError:
            continue
        for entity in facts.roles.get(obs_id, {}).get("subject", []):
            if entity in facts.entities:
                facts.entities[entity].opened_t = value
