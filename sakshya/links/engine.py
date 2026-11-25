from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import Any

import numpy as np
import pandas as pd

from sakshya.core.config import calibration_scale, settings
from sakshya.core.geo import haversine_m
from sakshya.core.identifiers import address_similarity, display, name_similarity
from sakshya.core.timeutil import fmt_ist
from sakshya.links.terms import agreement_term, finalize, place_term, time_term
from sakshya.model import Link, Term, make_id
from sakshya.normalise.facts import Facts

SAME_EVENT_FAMILIES = {
    "ref": {"window": 600.0, "mu": 3.0, "lag": 10.0, "label": "same transaction reference"},
    "amt": {"window": 900.0, "mu": 8.0, "lag": 15.0, "label": "same amount on the same account"},
    "atm": {"window": 600.0, "mu": 0.0, "lag": 10.0, "label": "same ATM and amount"},
    "atmcam": {"window": 600.0, "mu": 0.0, "lag": 20.0, "label": "camera event at the same ATM"},
    "call": {"window": 600.0, "mu": 0.0, "lag": 5.0, "label": "same pair of numbers"},
    "sms": {"window": 600.0, "mu": 2.0, "lag": 10.0, "label": "same pair of numbers"},
}


@dataclass
class LinkContext:
    obs: pd.DataFrame
    facts: Facts
    seeds: list[str]
    linked: dict[str, int]
    cfg: dict[str, Any]

    def row(self, obs_id: str) -> pd.Series:
        return self.obs.loc[obs_id]


def _fin(ctx: LinkContext, link: Link, cross_source: bool = True) -> Link:
    lc = ctx.cfg
    return finalize(
        link, lc["cap_per_source"], lc["accept_w"], lc["min_positive_sources"], calibration_scale(link.type), cross_source
    )


def same_event_links(ctx: LinkContext) -> list[Link]:
    obs = ctx.obs
    timed = obs[obs["t"].notna() & obs["anchors"].map(bool)]
    groups: dict[str, list[str]] = defaultdict(list)
    for obs_id, anchors in zip(timed.index, timed["anchors"]):
        for anchor in anchors:
            groups[anchor].append(obs_id)
    amount_freq: dict[str, Counter] = defaultdict(Counter)
    for anchor, members in groups.items():
        if anchor.startswith("amt:"):
            tail = anchor.split("|a4:")[-1]
            amount_freq[tail][anchor] += len(members)
    candidates: list[tuple[float, Link]] = []
    for anchor, members in groups.items():
        family = anchor.split(":", 1)[0]
        spec = SAME_EVENT_FAMILIES.get(family)
        if spec is None or len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            ra, rb = obs.loc[a], obs.loc[b]
            if ra["evidence_id"] == rb["evidence_id"]:
                continue
            dt = float(rb["t"] - ra["t"])
            if abs(dt) > spec["window"]:
                continue
            if family in {"ref", "amt"} and ra["kind"] == rb["kind"] == "txn" and ra["direction"] == rb["direction"]:
                continue
            first, second = (a, b) if dt >= 0 else (b, a)
            r1, r2 = obs.loc[first], obs.loc[second]
            gap = abs(dt)
            sigma2 = float(r1["sigma_t"]) ** 2 + float(r2["sigma_t"]) ** 2 + spec["lag"] ** 2
            terms = [time_term(gap, spec["mu"], sigma2, 2 * spec["window"], r2["evidence_id"], "Recorded times")]
            if family == "ref":
                terms.append(
                    agreement_term(
                        "reference", True, 0.99, 1e-6, r1["evidence_id"], f"Both records carry transaction reference {anchor[4:]}"
                    )
                )
            elif family == "amt":
                tail = anchor.split("|a4:")[-1]
                total = sum(amount_freq[tail].values()) or 1
                u = max(amount_freq[tail][anchor] / total, 0.01)
                terms.append(
                    agreement_term(
                        "amount",
                        True,
                        0.98,
                        u,
                        r1["evidence_id"],
                        f"Same amount and account ending {tail}; this amount is {u:.0%} of records on that account",
                    )
                )
            elif family == "atm":
                terms.append(agreement_term("atm_amount", True, 0.98, 0.05, r1["evidence_id"], "Same ATM and the same amount"))
            elif family == "atmcam":
                terms.append(
                    agreement_term(
                        "camera",
                        True,
                        0.95,
                        0.1,
                        r2["evidence_id"],
                        "Recorder logs a customer at this ATM; camera covers the cash slot",
                    )
                )
            elif family == "call":
                d1, d2 = r1["duration_s"], r2["duration_s"]
                if not (pd.isna(d1) or pd.isna(d2)):
                    agree = abs(float(d1) - float(d2)) <= 3
                    terms.append(
                        agreement_term(
                            "duration", agree, 0.95, 0.05, r2["evidence_id"], f"Durations {float(d1):.0f} s and {float(d2):.0f} s"
                        )
                    )
            link = Link(
                link_id=make_id("SE", *sorted([first, second])),
                type="same_event",
                a=first,
                b=second,
                a_kind="obs",
                b_kind="obs",
                claim=f"{_describe(r1)} and {_describe(r2)} record the same real event ({spec['label']})",
                terms=terms,
                basis=[first, second],
                sources=[r1["evidence_id"], r2["evidence_id"]],
                alternatives=["Two separate events that happen to match"],
                defeaters=["A third record showing these were distinct events"],
                extra={"family": family, "gap_s": gap},
            )
            _fin(ctx, link)
            candidates.append((link.w, link))
    candidates.sort(key=lambda item: -item[0])
    used: set[tuple[str, str]] = set()
    chosen = []
    for _, link in candidates:
        ea, eb = obs.loc[link.a, "evidence_id"], obs.loc[link.b, "evidence_id"]
        if (link.a, eb) in used or (link.b, ea) in used:
            continue
        used.add((link.a, eb))
        used.add((link.b, ea))
        chosen.append(link)
    return chosen


def _describe(row: pd.Series) -> str:
    labels = {
        "txn": "bank entry",
        "atm_withdrawal": "cash withdrawal",
        "sms": "SMS",
        "call": "call record",
        "cctv_event": "CCTV event",
        "chat": "chat message",
        "presence": "network presence",
        "location": "location fix",
        "email": "email",
    }
    return f"{labels.get(row['kind'], row['kind'])} {row.name}"


def cash_events(ctx: LinkContext, same_event: list[Link]) -> list[dict[str, Any]]:
    obs = ctx.obs
    statements = obs[(obs["kind"] == "atm_withdrawal") & (obs["source"] == "bank_statement")]
    journal_of: dict[str, str] = {}
    for link in same_event:
        if link.extra.get("family") == "atm":
            ka, kb = obs.loc[link.a, "source"], obs.loc[link.b, "source"]
            if ka == "bank_statement" and kb == "atm_journal":
                journal_of[link.a] = link.b
            elif kb == "bank_statement" and ka == "atm_journal":
                journal_of[link.b] = link.a
    roles = ctx.facts.roles
    events = []
    for obs_id, row in statements.iterrows():
        anchor_id = journal_of.get(obs_id, obs_id)
        anchor = obs.loc[anchor_id]
        if pd.isna(anchor["lat"]):
            continue
        holder = (roles.get(obs_id, {}).get("holder") or [None])[0]
        atm = (roles.get(obs_id, {}).get("atm") or [None])[0]
        events.append(
            {
                "event": anchor_id,
                "statement": obs_id,
                "t": float(anchor["t"]),
                "sigma": float(anchor["sigma_t"]),
                "lat": float(anchor["lat"]),
                "lon": float(anchor["lon"]),
                "r": float(anchor["radius_m"] or 20.0),
                "account": holder,
                "atm": atm,
                "amount": float(row["amount"] or 0.0),
                "evidence": [row["evidence_id"], anchor["evidence_id"]],
            }
        )
    return events


def _presence_index(ctx: LinkContext) -> pd.DataFrame:
    obs = ctx.obs
    mask = obs["lat"].notna() & obs["t"].notna() & obs["kind"].isin(["presence", "call", "sms", "location", "network_event"])
    frame = obs[mask & obs["source"].isin(["cdr", "tower_dump", "cloud_location"])].copy()
    entity = []
    for obs_id, source, attrs in zip(frame.index, frame["source"], frame["attrs"]):
        if source == "cloud_location":
            subject = (ctx.facts.roles.get(obs_id, {}).get("subject") or [None])[0]
            entity.append(subject)
        else:
            subscriber = attrs.get("subscriber")
            entity.append(f"phone:{subscriber}" if subscriber else None)
    frame["entity"] = entity
    return frame[frame["entity"].notna()]


def co_presence_links(ctx: LinkContext, events: list[dict[str, Any]]) -> tuple[list[Link], list[Link], list[dict[str, Any]]]:
    cfg = ctx.cfg
    window = float(cfg["copresence_window_s"])
    max_extra = float(cfg["copresence_distance_m"])
    area_radius = float(cfg["copresence_area_radius_m"])
    speed = float(cfg["speed_kmh"]) / 3.6
    presence = _presence_index(ctx)
    links: list[Link] = []
    impossible: list[Link] = []
    scored: list[dict[str, Any]] = []
    if presence.empty:
        return links, impossible, scored
    p_t = presence["t"].to_numpy()
    p_lat = presence["lat"].to_numpy()
    p_lon = presence["lon"].to_numpy()
    p_r = presence["radius_m"].fillna(1000.0).to_numpy()
    p_sigma = presence["sigma_t"].to_numpy()
    p_entity = presence["entity"].to_numpy()
    p_ids = presence.index.to_numpy()
    p_source = presence["evidence_id"].to_numpy()
    for event in events:
        near_time = np.abs(p_t - event["t"]) <= window
        best: dict[str, tuple[float, int, float]] = {}
        for index in np.nonzero(near_time)[0]:
            distance = haversine_m(event["lat"], event["lon"], p_lat[index], p_lon[index])
            if distance > event["r"] + p_r[index] + max_extra:
                continue
            score = abs(p_t[index] - event["t"]) / 300.0 + distance / max(p_r[index], 50.0)
            entity = p_entity[index]
            if entity not in best or score < best[entity][0]:
                best[entity] = (score, index, distance)
        phones = [e for e in best if e.startswith("phone:")]
        population = max(len(phones), 2)
        reach = [best[e][2] + p_r[best[e][1]] for e in phones] or [area_radius]
        block_radius = min(max(max(reach), 1000.0), area_radius)
        linked = [e for e in best if e in ctx.linked]
        for entity, (_, index, distance) in best.items():
            is_linked = entity in ctx.linked
            others_linked = sum(1 for e in linked if e != entity and e.startswith(entity.split(":")[0]))
            u = (others_linked + 1) / (population + 1)
            presence_id = p_ids[index]
            source = p_source[index]
            gap = float(p_t[index] - event["t"])
            sigma2 = event["sigma"] ** 2 + float(p_sigma[index]) ** 2 + 300.0**2
            terms = [
                time_term(gap, 0.0, sigma2, 2 * window, source, "Presence and withdrawal times"),
                place_term(distance, event["r"], float(p_r[index]), block_radius, source, "Presence and ATM locations"),
                agreement_term(
                    "rarity",
                    is_linked,
                    0.5,
                    u,
                    source,
                    f"{'Linked' if is_linked else 'Not linked'} to the case; {others_linked} of {population} other phones "
                    "present in that window are linked to the case",
                ),
            ]
            atm_label = display(event["atm"]) if event["atm"] else "the ATM"
            link = Link(
                link_id=make_id("CP", entity, event["event"]),
                type="co_presence",
                a=entity,
                b=event["event"],
                a_kind="entity",
                b_kind="obs",
                claim=(
                    f"The holder of {display(entity)} was near {atm_label} when Rs {event['amount']:,.0f} was withdrawn"
                    + (f" from {display(event['account'])}" if event["account"] else "")
                ),
                terms=terms,
                prior_odds=1.0 / max(population - 1, 1),
                basis=[presence_id, event["event"]],
                sources=[source, *event["evidence"]],
                alternatives=[f"Present by chance: {population} phones were seen on those cells in that window"],
                defeaters=[
                    f"Location evidence placing {display(entity)} elsewhere at {fmt_ist(event['t'])}",
                    "Evidence that the handset was with someone else",
                ],
                extra={
                    "population": population,
                    "distance_m": round(distance),
                    "gap_s": round(gap),
                    "linked": is_linked,
                    "block_radius_m": round(block_radius),
                    "event_t": event["t"],
                    "account": event["account"],
                    "atm": event["atm"],
                    "amount": event["amount"],
                },
            )
            _fin(ctx, link)
            scored.append(
                {"entity": entity, "event": event["event"], "w": link.w, "prior_odds": link.prior_odds, "linked": is_linked}
            )
            if is_linked:
                links.append(link)
        for entity in set(p_entity):
            if entity not in ctx.linked or entity in best:
                continue
            mask = (p_entity == entity) & (np.abs(p_t - event["t"]) <= 1800)
            for index in np.nonzero(mask)[0]:
                distance = haversine_m(event["lat"], event["lon"], p_lat[index], p_lon[index])
                gap = abs(p_t[index] - event["t"])
                reachable = speed * gap + event["r"] + p_r[index] + 2000
                if distance > reachable:
                    link = Link(
                        link_id=make_id("IM", entity, event["event"]),
                        type="impossibility",
                        a=entity,
                        b=event["event"],
                        a_kind="entity",
                        b_kind="obs",
                        claim=(
                            f"The holder of {display(entity)} could not have been at the withdrawal: "
                            f"their phone was {distance / 1000:.0f} km away {gap / 60:.0f} min before or after it"
                        ),
                        terms=[
                            Term(
                                "travel",
                                float(cfg["impossibility_w"]),
                                p_source[index],
                                f"{distance / 1000:.1f} km in {gap / 60:.1f} min needs more than {cfg['speed_kmh']} km/h",
                            )
                        ],
                        basis=[p_ids[index], event["event"]],
                        sources=[p_source[index], *event["evidence"]],
                        alternatives=["Handset carried by someone else while its owner was at the ATM"],
                        defeaters=["Evidence that the phone was not with its registered holder"],
                        extra={
                            "distance_m": round(distance),
                            "gap_s": round(gap),
                            "event_t": event["t"],
                            "account": event["account"],
                        },
                    )
                    _fin(ctx, link)
                    impossible.append(link)
                    break
    return links, impossible, scored


def same_actor_links(ctx: LinkContext) -> list[Link]:
    facts = ctx.facts
    obs = ctx.obs
    links: list[Link] = []
    for phone, sims in facts.sims_by_phone.items():
        keep = facts.kyc_imsi.get(phone)
        chosen = [keep] if keep in sims else ([sorted(sims)[0]] if len(sims) == 1 else [])
        for sim in chosen:
            links.append(_observed(phone, sim, "SIM card in use on this number", _basis_for(facts, phone, sim)))
    for upi, account in facts.upi_account.items():
        links.append(_observed(account, upi, "UPI ID mapped to this account in bank records", []))
    if not facts.edges.empty:
        for cloud, phone, obs_id in facts.edges[facts.edges["kind"] == "device_phone"][["src", "dst", "obs_id"]].itertuples(
            index=False
        ):
            links.append(_observed(cloud, phone, "Phone number registered on the cloud account's device", [obs_id]))
    for imei, users in facts.handset_users.items():
        members = sorted(users)
        if len(members) == 1:
            links.append(_observed(members[0], imei, "Handset used only with this SIM", users[members[0]][:1]))
        for a, b in combinations(members, 2):
            oa, ob = users[a][0], users[b][0]
            ea, eb = obs.loc[oa, "evidence_id"], obs.loc[ob, "evidence_id"]
            terms = [
                agreement_term(
                    "handset",
                    True,
                    0.9,
                    0.001,
                    ea,
                    f"Both SIMs were used in handset {imei}; unrelated people rarely share a handset",
                )
            ]
            link = Link(
                make_id("SA", "handset", *sorted([a, b])),
                "same_actor",
                a,
                b,
                "entity",
                "entity",
                claim=f"{display(a)} and {display(b)} are used by the same person (shared handset {imei})",
                terms=terms,
                basis=[oa, ob],
                sources=[ea, eb],
                alternatives=["Handset sold or lent to another person between uses"],
                defeaters=["Purchase or transfer record for the handset", "Overlapping use in two places at once"],
                extra={"basis": "shared_handset", "imei": imei},
            )
            links.append(_fin(ctx, link))
    seeds = sorted(set(ctx.seeds))
    for a, b in pairwise(seeds):
        links.append(_observed(a, b, "Complainant's own identifiers named in the complaint", []))
    links += _kyc_links(ctx)
    links += _seizure_links(ctx)
    links += _network_links(ctx)
    links += _co_travel_links(ctx)
    return links


def _basis_for(facts: Facts, a: str, b: str) -> list[str]:
    found = facts.first_edge_obs.get((a, b))
    return [found] if found else []


def _observed(a: str, b: str, detail: str, basis: list[str]) -> Link:
    return Link(
        make_id("SA", "obs", *sorted([a, b])),
        "same_actor",
        a,
        b,
        "entity",
        "entity",
        claim=f"{display(a)} and {display(b)} belong together ({detail.lower()})",
        terms=[Term("record", 4.0, "record", detail)],
        w=4.0,
        raw_w=4.0,
        basis=basis,
        sources=["record"],
        status="observed",
        extra={"basis": "record"},
    )


def _kyc_links(ctx: LinkContext) -> list[Link]:
    obs = ctx.obs
    kyc = obs[obs["kind"] == "kyc"]
    records = []
    for obs_id, row in kyc.iterrows():
        subject = ctx.facts.roles.get(obs_id, {}).get("subject", [])
        if not subject:
            continue
        records.append((obs_id, row["evidence_id"], subject[0], row["attrs"].get("name", ""), row["attrs"].get("address", "")))
    pairs: dict[frozenset[str], dict[str, Any]] = {}

    def slot(a: str, b: str) -> dict[str, Any]:
        key = frozenset({a, b})
        if key not in pairs:
            pairs[key] = {"a": min(a, b), "b": max(a, b), "terms": [], "basis": [], "sources": [], "registered": False}
        return pairs[key]

    for account, phone in ctx.facts.registered_phone.items():
        basis = _basis_for(ctx.facts, account, phone)
        source = obs.loc[basis[0], "evidence_id"] if basis else "kyc"
        entry = slot(account, phone)
        entry["registered"] = True
        entry["terms"].append(
            agreement_term("registered_phone", True, 0.9, 0.02, source, "Bank KYC lists this number for the account holder")
        )
        entry["basis"] += basis
        entry["sources"].append(source)
    n = max(len(records), 1)
    for i, j in combinations(range(len(records)), 2):
        oa, ea, sa, na, aa = records[i]
        ob, eb, sb, nb, ab = records[j]
        if sa == sb or not na or not nb:
            continue
        sim = name_similarity(na, nb)
        if sim < 0.85:
            continue
        name_u = max(sum(1 for r in records if name_similarity(na, r[3]) >= 0.85) / n, 1.0 / n)
        addr_sim = address_similarity(aa, ab)
        addr_u = max(sum(1 for r in records if address_similarity(aa, r[4]) >= 0.85) / n, 1.0 / n)
        entry = slot(sa, sb)
        entry["terms"].append(
            agreement_term(
                "name",
                True,
                0.9,
                name_u,
                ea,
                f"Registered names '{na}' and '{nb}' match ({sim:.0%}); {name_u:.0%} of KYC records carry a matching name",
            )
        )
        entry["terms"].append(
            agreement_term("address", addr_sim >= 0.85, 0.8, addr_u, eb, f"Registered addresses match {addr_sim:.0%}")
        )
        entry["basis"] += [oa, ob]
        entry["sources"] += [ea, eb]
    links = []
    for entry in pairs.values():
        a, b = entry["a"], entry["b"]
        account, phone = (a, b) if a.startswith("account:") else (b, a)
        claim = (
            f"{display(phone)} is the phone of the holder of {display(account)}"
            if entry["registered"]
            else f"{display(a)} and {display(b)} are registered to the same person"
        )
        link = Link(
            make_id("SA", "kyc", a, b),
            "same_actor",
            a,
            b,
            "entity",
            "entity",
            claim=claim,
            terms=entry["terms"],
            basis=list(dict.fromkeys(entry["basis"])),
            sources=list(dict.fromkeys(entry["sources"])),
            alternatives=["Different people with a common name", "Number belongs to an agent or relative who opened the account"],
            defeaters=["Identity documents showing different people"],
            extra={"basis": "registered_phone" if entry["registered"] else "kyc_name"},
        )
        links.append(_fin(ctx, link))
    return links


def _seizure_links(ctx: LinkContext) -> list[Link]:
    obs = ctx.obs
    seized = obs[obs["kind"] == "seizure"]
    links = []
    groups: dict[str, list[tuple[str, list[str], str]]] = defaultdict(list)
    for obs_id, row in seized.iterrows():
        items = ctx.facts.roles.get(obs_id, {}).get("item", [])
        groups[str(row["place"]).strip().lower()].append((obs_id, items, row["evidence_id"]))
        for a, b in combinations(sorted(items), 2):
            links.append(_observed(a, b, f"Same seized item ({row['attrs'].get('item_type', 'item')})", [obs_id]))
    kyc = obs[obs["kind"] == "kyc"]
    for premises, members in groups.items():
        for (oa, ia, ea), (ob, ib, _) in combinations(members, 2):
            if not ia or not ib:
                continue
            a, b = ia[0], ib[0]
            terms = [agreement_term("premises", True, 0.85, 0.02, ea, "Seized together from the same premises in one search")]
            for kyc_id, kyc_row in kyc.iterrows():
                subject = ctx.facts.roles.get(kyc_id, {}).get("subject", [])
                if (
                    any(s in ia + ib for s in subject)
                    and address_similarity(premises, kyc_row["attrs"].get("address", "")) >= 0.85
                ):
                    terms.append(
                        agreement_term(
                            "kyc_address",
                            True,
                            0.8,
                            0.05,
                            kyc_row["evidence_id"],
                            "Premises address matches the KYC address of a seized SIM",
                        )
                    )
                    break
            sources = [ea] + [t.source for t in terms[1:]]
            link = Link(
                make_id("SA", "seized", *sorted([a, b])),
                "same_actor",
                a,
                b,
                "entity",
                "entity",
                claim=f"{display(a)} and {display(b)} were seized together and are used by one person",
                terms=terms,
                basis=[oa, ob],
                sources=sources,
                alternatives=["Devices belong to different members of the household"],
                defeaters=["Statements or purchase records tying the devices to different people"],
                extra={"basis": "seizure"},
            )
            links.append(_fin(ctx, link))
    return links


def _registrable(domain: str) -> str:
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _network_links(ctx: LinkContext) -> list[Link]:
    facts = ctx.facts
    obs = ctx.obs
    links: list[Link] = []
    if facts.edges.empty:
        return links
    connected = facts.edges[facts.edges["kind"] == "connected"]
    hosts = facts.edges[facts.edges["kind"] == "connected_host"]
    emails = obs[obs["kind"] == "email"]
    device_count_for_domain: dict[str, set[str]] = defaultdict(set)
    host_obs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mac, host, obs_id in hosts[["src", "dst", "obs_id"]].itertuples(index=False):
        key = _registrable(host.split(":", 1)[1])
        device_count_for_domain[key].add(mac)
        host_obs[(mac, key)].append(obs_id)
    for obs_id, row in emails.iterrows():
        roles = facts.roles.get(obs_id, {})
        senders = roles.get("from", [])
        domains = {_registrable(e.split("@", 1)[1]) for e in senders if "@" in e}
        domains |= {_registrable(d.split(":", 1)[1]) for d in roles.get("mentioned", []) if d.startswith("domain:")}
        for sender in senders:
            for (mac, key), flows in host_obs.items():
                if key not in domains:
                    continue
                devices = len(device_count_for_domain[key])
                u = 0.005 if devices <= 1 else min(0.5, 0.005 * devices * 5)
                source = obs.loc[flows[0], "evidence_id"]
                terms = [
                    agreement_term(
                        "domain",
                        True,
                        0.85,
                        u,
                        source,
                        f"Device contacted {key} {len(flows)} times; the email came from or linked to the same domain",
                    )
                ]
                link = Link(
                    make_id("SA", "infra", mac, sender),
                    "same_actor",
                    mac,
                    sender,
                    "entity",
                    "entity",
                    claim=f"The operator of {display(mac)} controls {display(sender)} (shared infrastructure {key})",
                    terms=terms,
                    basis=[flows[0], obs_id],
                    sources=[source, row["evidence_id"]],
                    alternatives=["Device belongs to a victim who visited the same site"],
                    defeaters=["Device only visited the site after the email, like a victim would"],
                    extra={"basis": "infrastructure", "domain": key, "flows": len(flows)},
                )
                links.append(_fin(ctx, link))
        for ip in roles.get("sender_ip", []):
            matches = connected[connected["dst"] == ip]
            for mac, group in matches.groupby("src"):
                flow_ids = group["obs_id"].tolist()
                source = obs.loc[flow_ids[0], "evidence_id"]
                near = obs.loc[flow_ids, "t"].sub(row["t"]).abs().min() if not pd.isna(row["t"]) else float("inf")
                terms = [
                    agreement_term(
                        "ip", True, 0.6, 0.01, source, f"Device connected to {display(ip)}, the address the email was sent from"
                    )
                ]
                terms.append(
                    agreement_term(
                        "ip_time",
                        near <= 1800,
                        0.7,
                        0.15,
                        row["evidence_id"],
                        f"Nearest session to that address was {near / 60:.0f} min from the email",
                    )
                )
                sender = senders[0] if senders else None
                if sender is None:
                    continue
                link = Link(
                    make_id("SA", "ip", mac, sender),
                    "same_actor",
                    mac,
                    sender,
                    "entity",
                    "entity",
                    claim=f"{display(mac)} sent email as {display(sender)} (shared IP {display(ip)})",
                    terms=terms,
                    basis=[flow_ids[0], obs_id],
                    sources=[source, row["evidence_id"]],
                    alternatives=["The address is a shared VPN or proxy exit used by many people"],
                    defeaters=["Provider records showing the address is a shared exit"],
                    extra={"basis": "shared_ip", "ip": ip},
                )
                links.append(_fin(ctx, link))
    return links


def _co_travel_links(ctx: LinkContext) -> list[Link]:
    obs = ctx.obs
    frame = obs[(obs["source"] == "cdr") & obs["t"].notna()]
    slots: dict[str, dict[int, str]] = defaultdict(dict)
    sources: dict[str, str] = {}
    for obs_id, row in frame.iterrows():
        subscriber = row["attrs"].get("subscriber")
        cell = (ctx.facts.roles.get(obs_id, {}).get("cell") or [None])[0]
        if subscriber and cell:
            slots[f"phone:{subscriber}"][int(row["t"] // 900)] = cell
            sources[f"phone:{subscriber}"] = row["evidence_id"]
    links = []
    p1, p0 = 0.8, 0.05
    for a, b in combinations(sorted(slots), 2):
        shared = set(slots[a]) & set(slots[b])
        if len(shared) < 3:
            continue
        k = sum(1 for s in shared if slots[a][s] == slots[b][s])
        n = len(shared)
        w = k * math.log10(p1 / p0) + (n - k) * math.log10((1 - p1) / (1 - p0))
        terms = [Term("co_travel", w, sources[a], f"Seen on the same cell in {k} of {n} shared 15-minute slots")]
        link = Link(
            make_id("SA", "travel", a, b),
            "same_actor",
            a,
            b,
            "entity",
            "entity",
            claim=f"{display(a)} and {display(b)} move together",
            terms=terms,
            basis=[],
            sources=[sources[a], sources[b]],
            alternatives=["Two people who live or work together"],
            defeaters=["Periods where the phones separate"],
            extra={"basis": "co_travel", "slots": n, "same": k},
        )
        links.append(_fin(ctx, link))
    return links


def build_context(obs: pd.DataFrame, facts: Facts, seeds: list[str], linked: dict[str, int]) -> LinkContext:
    indexed = obs.set_index("obs_id", drop=False)
    return LinkContext(indexed, facts, seeds, linked, settings()["links"])
