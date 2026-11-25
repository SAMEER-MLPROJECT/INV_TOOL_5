from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import pandas as pd

from sakshya.core.identifiers import canonical, display

EDGE_COLUMNS = ["src", "dst", "kind", "obs_id", "t", "amount"]
COMM_KINDS = {"called", "texted", "messaged", "emailed"}


@dataclass
class EntityInfo:
    entity: str
    kind: str
    value: str
    label: str
    obs: int = 0
    sources: set[str] = field(default_factory=set)
    names: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    kyc_obs: list[str] = field(default_factory=list)
    first_t: float | None = None
    last_t: float | None = None
    case_relevant: bool = False
    opened_t: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "kind": self.kind,
            "value": self.value,
            "label": self.label,
            "obs": self.obs,
            "sources": sorted(self.sources),
            "names": self.names,
            "addresses": self.addresses,
            "kyc_obs": self.kyc_obs,
            "first_t": self.first_t,
            "last_t": self.last_t,
            "case_relevant": self.case_relevant,
            "opened_t": self.opened_t,
        }


@dataclass
class Facts:
    edges: pd.DataFrame
    entities: dict[str, EntityInfo]
    roles: dict[str, dict[str, list[str]]]
    sims_by_phone: dict[str, set[str]]
    handset_users: dict[str, dict[str, list[str]]]
    kyc_imsi: dict[str, str]
    upi_account: dict[str, str]
    registered_phone: dict[str, str]
    lan_ip_mac: dict[str, str]
    first_edge_obs: dict[tuple[str, str], str]


def obs_roles(ids: pd.DataFrame) -> dict[str, dict[str, list[str]]]:
    roles: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for obs_id, role, entity in zip(ids["obs_id"], ids["role"], ids["entity"]):
        roles[obs_id][role].append(entity)
    return {k: dict(v) for k, v in roles.items()}


def build_facts(obs: pd.DataFrame, ids: pd.DataFrame) -> Facts:
    roles = obs_roles(ids)
    edges: list[dict[str, Any]] = []
    entities: dict[str, EntityInfo] = {}
    sims_by_phone: dict[str, set[str]] = defaultdict(set)
    handset_users: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    kyc_imsi: dict[str, str] = {}
    upi_account: dict[str, str] = {}
    registered_phone: dict[str, str] = {}
    lan_ip_mac: dict[str, str] = {}

    def edge(src: str, dst: str, kind: str, obs_id: str, t: float | None, amount: float | None = None) -> None:
        if src and dst and src != dst:
            edges.append({"src": src, "dst": dst, "kind": kind, "obs_id": obs_id, "t": t, "amount": amount})

    for row in obs.itertuples(index=False):
        r = roles.get(row.obs_id, {})
        t = None if pd.isna(row.t) else float(row.t)
        for role_entities in r.values():
            for entity in role_entities:
                info = entities.get(entity)
                if info is None:
                    kind, _, value = entity.partition(":")
                    info = entities[entity] = EntityInfo(entity, kind, value, display(entity))
                info.obs += 1
                info.sources.add(row.evidence_id)
                if t is not None:
                    info.first_t = t if info.first_t is None else min(info.first_t, t)
                    info.last_t = t if info.last_t is None else max(info.last_t, t)
                if not (row.source == "tower_dump" and row.kind == "presence"):
                    info.case_relevant = True
        kind = row.kind
        if kind == "txn":
            holder = (r.get("holder") or [None])[0]
            cps = r.get("counterparty", [])
            cp_account = next((e for e in cps if e.startswith("account:")), None)
            cp_upi = next((e for e in cps if e.startswith("upi:")), None)
            counterparty = cp_account or cp_upi
            if cp_account and cp_upi:
                upi_account[cp_upi] = cp_account
            if holder and counterparty:
                if row.direction == "DR":
                    edge(holder, counterparty, "paid", row.obs_id, t, row.amount)
                else:
                    edge(counterparty, holder, "paid", row.obs_id, t, row.amount)
        elif kind == "atm_withdrawal":
            holder = (r.get("holder") or [None])[0]
            atm = (r.get("atm") or [None])[0]
            if holder and atm:
                edge(holder, atm, "withdrew_cash", row.obs_id, t, row.amount)
        elif kind in {"call", "sms", "chat", "email"}:
            label = {"call": "called", "sms": "texted", "chat": "messaged", "email": "emailed"}[kind]
            for src in r.get("from", []):
                for dst in r.get("to", []):
                    edge(src, dst, label, row.obs_id, t)
            for ip in r.get("sender_ip", []):
                for src in r.get("from", []):
                    edge(ip, src, "sent_via", row.obs_id, t)
        if row.source in {"cdr", "tower_dump"}:
            subscriber = row.attrs.get("subscriber")
            phone = f"phone:{subscriber}" if subscriber else None
            imei = (r.get("device") or [None])[0]
            imsi = (r.get("sim") or [None])[0]
            cell = (r.get("cell") or [None])[0]
            if phone and imsi:
                sims_by_phone[phone].add(imsi)
                edge(phone, imsi, "sim_in_use", row.obs_id, t)
            user = imsi or phone
            if imei and user:
                handset_users[imei][user].append(row.obs_id)
                edge(user, imei, "used_handset", row.obs_id, t)
            if phone and cell and kind in {"presence", "call", "sms", "network_event"}:
                edge(phone, cell, "seen_at", row.obs_id, t)
        if kind == "kyc":
            subjects = r.get("subject", [])
            name = row.attrs.get("name", "")
            address = row.attrs.get("address", "")
            for entity in subjects:
                info = entities[entity]
                if name and name not in info.names:
                    info.names.append(name)
                if address and address not in info.addresses:
                    info.addresses.append(address)
                info.kyc_obs.append(row.obs_id)
            phones = [e for e in subjects if e.startswith("phone:")]
            sims = r.get("sim", [])
            if phones and sims:
                kyc_imsi[phones[0]] = sims[0]
            accounts = [e for e in subjects if e.startswith("account:")]
            upis = [e for e in subjects if e.startswith("upi:")]
            if accounts and upis:
                upi_account[upis[0]] = accounts[0]
            if accounts and r.get("registered_phone"):
                registered_phone[accounts[0]] = r["registered_phone"][0]
                edge(accounts[0], r["registered_phone"][0], "registered_phone", row.obs_id, t)
        elif kind == "account_link":
            for cloud in r.get("subject", []):
                for phone in r.get("device_phone", []):
                    edge(cloud, phone, "device_phone", row.obs_id, t)
        elif kind == "net_flow":
            mac = (r.get("device") or [None])[0]
            for ip in r.get("lan_ip", []):
                if mac:
                    lan_ip_mac[ip] = mac
            if mac:
                for ip in r.get("dst", []):
                    edge(mac, ip, "connected", row.obs_id, t)
                for host in r.get("dst_host", []):
                    edge(mac, host, "connected_host", row.obs_id, t)
        elif kind == "net_incident":
            for host in r.get("host", []):
                for dst in r.get("dst", []):
                    edge(host, dst, "incident", row.obs_id, t)
    for upi, account in upi_account.items():
        edge(upi, account, "upi_of", "", None)
    frame = pd.DataFrame(edges, columns=EDGE_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["src", "dst", "kind", "obs_id"])
    first_edge_obs: dict[tuple[str, str], str] = {}
    for item in edges:
        if item["obs_id"]:
            first_edge_obs.setdefault((item["src"], item["dst"]), item["obs_id"])
    return Facts(
        frame,
        entities,
        roles,
        dict(sims_by_phone),
        {k: dict(v) for k, v in handset_users.items()},
        kyc_imsi,
        upi_account,
        registered_phone,
        lan_ip_mac,
        first_edge_obs,
    )


def seed_entities(manifest: dict[str, Any], facts: Facts) -> list[str]:
    seeds = []
    for item in (manifest.get("seed") or {}).get("identifiers", []):
        identifier = canonical(item.get("type", ""), item.get("value", ""))
        if identifier is not None:
            seeds.append(identifier.entity)
    expanded = list(seeds)
    for entity in seeds:
        if entity.startswith("account:"):
            expanded += [u for u, a in facts.upi_account.items() if a == entity]
    return list(dict.fromkeys(expanded))


def case_linked(facts: Facts, seeds: list[str], depth: int) -> dict[str, int]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    if not facts.edges.empty:
        relevant = facts.edges[facts.edges["kind"].isin(COMM_KINDS | {"paid", "upi_of"})]
        for src, dst in zip(relevant["src"], relevant["dst"]):
            adjacency[src].add(dst)
            adjacency[dst].add(src)
    distance = dict.fromkeys(seeds, 0)
    frontier = list(seeds)
    for level in range(1, depth + 1):
        nxt = []
        for node in frontier:
            for other in adjacency.get(node, ()):
                if other not in distance:
                    distance[other] = level
                    nxt.append(other)
        frontier = nxt
    for account, phone in facts.registered_phone.items():
        if account in distance and phone not in distance:
            distance[phone] = distance[account] + 1
    imsi_phone = defaultdict(set)
    for phone, sims in facts.sims_by_phone.items():
        for sim in sims:
            imsi_phone[sim].add(phone)
    for users in facts.handset_users.values():
        members = list(users)
        linked = [u for u in members if u in distance or any(p in distance for p in imsi_phone.get(u, ()))]
        if linked:
            base = min(distance.get(u, min((distance.get(p, 9) for p in imsi_phone.get(u, ())), default=9)) for u in linked)
            for user in members:
                for target in [user, *imsi_phone.get(user, ())]:
                    distance.setdefault(target, base + 1)
    if not facts.edges.empty:
        devices = facts.edges[facts.edges["kind"] == "device_phone"]
        for cloud, phone in zip(devices["src"], devices["dst"]):
            if phone in distance:
                distance.setdefault(cloud, distance[phone])
    return distance


def pairs(items: list[str]) -> list[tuple[str, str]]:
    return list(combinations(sorted(items), 2))
