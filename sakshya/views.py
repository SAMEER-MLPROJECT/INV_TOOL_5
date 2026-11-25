from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

import pandas as pd

from sakshya.core.config import colmap
from sakshya.core.identifiers import DISPLAY_NAMES, display, kind_of
from sakshya.core.timeutil import fmt_ist
from sakshya.model import verbal

if TYPE_CHECKING:
    from sakshya.pipeline import Analysis

CONTEXT_BEFORE_S = 3 * 86400.0
CONTEXT_AFTER_S = 2 * 86400.0
KIND_TITLES = {
    "txn": "Bank transaction",
    "atm_withdrawal": "Cash withdrawal",
    "call": "Call",
    "sms": "SMS",
    "chat": "Chat message",
    "email": "Email",
    "presence": "Network presence",
    "location": "Location fix",
    "cctv_event": "CCTV event",
    "net_flow": "Network connection",
    "net_incident": "Network incident",
    "seizure": "Seizure",
    "complaint": "Complaint",
    "testimony": "Statement",
    "kyc": "KYC record",
    "network_event": "SIM event",
    "account_link": "Account link",
}
OBSERVED_GRAPH_KINDS = {
    "paid",
    "called",
    "messaged",
    "emailed",
    "texted",
    "withdrew_cash",
    "used_handset",
    "registered_phone",
    "device_phone",
    "upi_of",
    "sim_in_use",
}


def interesting_persons(analysis: Analysis) -> dict[str, list[str]]:
    view = analysis.view
    roles: dict[str, list[str]] = defaultdict(list)
    for hypothesis in analysis.explained["hypotheses"][:4]:
        for role in hypothesis.get("roles", []):
            for unit in role["units"]:
                person = unit if unit.startswith("P") and unit[1:].isdigit() else view.entity_person.get(unit)
                if person:
                    tag = f"{role['label']} ({hypothesis['id']})"
                    if tag not in roles[person]:
                        roles[person].append(tag)
    for link in analysis.links:
        if (
            link.type in {"co_presence", "impossibility"}
            and link.status in {"inferred", "confirmed"}
            and link.a in view.entity_person
        ):
            roles.setdefault(view.entity_person[link.a], [])
    for account in analysis.taint.accounts:
        if account in view.entity_person:
            roles.setdefault(view.entity_person[account], [])
    for indicator in view.indicators.all():
        if indicator.entity in view.entity_person:
            roles.setdefault(view.entity_person[indicator.entity], [])
    for seed in analysis.seeds:
        if seed in view.entity_person:
            roles.setdefault(view.entity_person[seed], [])
    return dict(roles)


def build_people(analysis: Analysis) -> list[dict[str, Any]]:
    view = analysis.view
    links_by_id = {link.link_id: link for link in analysis.links}
    cleared = {link.a for link in analysis.links if link.type == "impossibility" and link.status in {"inferred", "confirmed"}}
    people = []
    for person_id, roles in interesting_persons(analysis).items():
        person = view.person(person_id)
        members = []
        for entity, score in person.members.items():
            via = person.via.get(entity)
            link = links_by_id.get(via) if via else None
            info = analysis.facts.entities.get(entity)
            members.append(
                {
                    "entity": entity,
                    "kind": kind_of(entity),
                    "kind_label": DISPLAY_NAMES.get(kind_of(entity), kind_of(entity)),
                    "label": display(entity),
                    "score": score,
                    "via": via,
                    "via_claim": link.claim if link else ("Named in the complaint" if entity in analysis.seeds else ""),
                    "names": info.names if info else [],
                }
            )
        indicators = [i.to_dict() for i in view.indicators.of(set(person.members)).values()]
        people.append(
            {
                "id": person_id,
                "label": person.label,
                "names": person.names,
                "is_seed": person.is_seed,
                "roles": roles,
                "members": members,
                "indicators": indicators,
                "cleared": sorted(set(person.members) & cleared),
            }
        )
    people.sort(key=lambda p: (not p["is_seed"], not p["roles"], p["id"]))
    return people


def summarise_links(analysis: Analysis) -> list[dict[str, Any]]:
    interesting = set(interesting_persons(analysis))
    entity_person = analysis.view.entity_person
    rows = []
    for link in analysis.links:
        if link.type == "same_actor":
            if link.status == "observed" and entity_person.get(link.a) not in interesting:
                continue
            if link.status == "weak" and not (
                entity_person.get(link.a) in interesting or entity_person.get(link.b) in interesting
            ):
                continue
        data = link.to_dict()
        data["a_label"] = _end_label(analysis, link.a, link.a_kind)
        data["b_label"] = _end_label(analysis, link.b, link.b_kind)
        rows.append(data)
    order = {"co_presence": 0, "impossibility": 1, "same_actor": 2, "sequence": 3, "same_event": 4}
    rows.sort(key=lambda r: (order.get(r["type"], 9), -r["w"]))
    return rows


def _end_label(analysis: Analysis, value: str, kind: str) -> str:
    if kind == "obs" and value in analysis.obs.index:
        row = analysis.obs.loc[value]
        return f"{KIND_TITLES.get(row['kind'], row['kind'])} {value} at {fmt_ist(row['t'])}"
    return display(value)


def observation_detail(analysis: Analysis, obs_id: str) -> dict[str, Any] | None:
    if obs_id not in analysis.obs.index:
        return None
    row = analysis.obs.loc[obs_id]
    evidence = next(e for e in analysis.evidence if e.evidence_id == row["evidence_id"])
    clock = analysis.clocks.get(row["evidence_id"])
    roles = analysis.facts.roles.get(obs_id, {})
    return {
        "obs_id": obs_id,
        "kind": row["kind"],
        "title": KIND_TITLES.get(row["kind"], row["kind"]),
        "evidence_id": row["evidence_id"],
        "file": evidence.file,
        "source": evidence.source,
        "source_label": evidence.label,
        "sha256": evidence.sha256,
        "row": int(row["row"]),
        "raw": row["raw"],
        "text": row["text"],
        "t": None if pd.isna(row["t"]) else float(row["t"]),
        "t_raw": None if pd.isna(row["t_raw"]) else float(row["t_raw"]),
        "t_display": fmt_ist(row["t"]) if not pd.isna(row["t"]) else "",
        "t_raw_display": fmt_ist(row["t_raw"]) if not pd.isna(row["t_raw"]) else "",
        "sigma_t": float(row["sigma_t"]),
        "place": row["place"],
        "lat": _num(row["lat"]),
        "lon": _num(row["lon"]),
        "radius_m": _num(row["radius_m"]),
        "amount": _num(row["amount"]),
        "direction": row["direction"],
        "identifiers": [
            {"role": role, "entity": e, "label": display(e), "kind": kind_of(e)} for role, items in roles.items() for e in items
        ],
        "clock": clock.to_dict() if clock else None,
        "attrs": row["attrs"],
    }


def link_detail(analysis: Analysis, link_id: str) -> dict[str, Any] | None:
    link = next((l for l in analysis.links if l.link_id == link_id), None)
    if link is None:
        return None
    data = link.to_dict()
    data["a_label"] = _end_label(analysis, link.a, link.a_kind)
    data["b_label"] = _end_label(analysis, link.b, link.b_kind)
    data["basis_detail"] = [observation_detail(analysis, o) for o in link.basis if o in analysis.obs.index]
    evidence = {e.evidence_id: e for e in analysis.evidence}
    terms = []
    for term in link.terms:
        item = term.to_dict()
        source = evidence.get(term.source)
        item["source_label"] = f"{source.evidence_id} {source.file}" if source else term.source
        terms.append(item)
    data["terms"] = terms
    return data


def _num(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _summary(analysis: Analysis, obs_id: str) -> str:
    row = analysis.obs.loc[obs_id]
    roles = analysis.facts.roles.get(obs_id, {})
    kind = row["kind"]
    if kind == "txn":
        holder = (roles.get("holder") or [""])[0]
        cp = (roles.get("counterparty") or [""])[0]
        debit = row["direction"] == "DR"
        arrow = "to" if debit else "from"
        return f"Rs {row['amount']:,.0f} {'debited' if debit else 'credited'}: {display(holder)} {arrow} {display(cp)}"
    if kind == "atm_withdrawal":
        holder = (roles.get("holder") or [""])[0]
        atm = (roles.get("atm") or [""])[0]
        return f"Rs {row['amount']:,.0f} withdrawn from {display(holder)} at {display(atm)}"
    if kind in {"call", "sms", "chat", "email"}:
        src = ", ".join(display(e) for e in roles.get("from", []))
        dst = ", ".join(display(e) for e in roles.get("to", []))
        text = str(row["text"] or row["attrs"].get("subject", ""))[:140]
        return f"{src} to {dst}" + (f": {text}" if text else "")
    if kind == "presence":
        subscriber = row["attrs"].get("subscriber", "")
        return f"{subscriber} on cell {row['place']}"
    if kind == "location":
        return f"Location fix within {row['radius_m']:.0f} m"
    if kind == "cctv_event":
        return f"{row['attrs'].get('event', 'Event')} at {row['place']}"
    if kind == "net_flow":
        device = display((roles.get("device") or [""])[0])
        target = row["attrs"].get("dst_host") or display((roles.get("dst") or [""])[0])
        return f"{device} to {target}"
    if kind == "net_incident":
        return f"{row['attrs'].get('label', '')} incident: {row['text']}"
    if kind == "seizure":
        return f"Seized {row['attrs'].get('item_type', 'item')} at {row['attrs'].get('premises', '')}"
    if kind == "network_event":
        return f"SIM activation on {row['attrs'].get('subscriber', '')} at {row['place']}"
    return str(row["text"])[:160]


def build_timeline(analysis: Analysis, hypothesis: dict[str, Any] | None) -> dict[str, Any]:
    obs = analysis.obs
    phase_of: dict[str, str] = {}
    phase_labels: dict[str, str] = {}
    if hypothesis:
        for phase in hypothesis.get("phases", []):
            phase_labels[phase["name"]] = phase["label"]
            for obs_id in phase.get("events", []):
                phase_of[obs_id] = phase["name"]
    chosen: dict[str, str] = dict(phase_of)
    seed_set = set(analysis.seeds)
    for obs_id, roles in analysis.facts.roles.items():
        parties = set(roles.get("from", [])) | set(roles.get("to", []))
        if parties & seed_set and obs_id in obs.index and obs.at[obs_id, "kind"] in {"call", "chat", "email", "sms"}:
            chosen.setdefault(obs_id, "context")
    for link in analysis.links:
        if link.type in {"co_presence", "impossibility", "same_event"} and link.status in {"inferred", "confirmed"}:
            if link.type == "same_event" and not (set(link.basis) & set(chosen)):
                continue
            for obs_id in link.basis:
                chosen.setdefault(obs_id, "context")
    for kind in ("complaint", "seizure", "net_incident", "email"):
        for obs_id in obs[obs["kind"] == kind].index:
            chosen.setdefault(obs_id, "context")
    items = []
    for obs_id, phase in chosen.items():
        if obs_id not in obs.index:
            continue
        row = obs.loc[obs_id]
        if pd.isna(row["t"]):
            continue
        clock = analysis.clocks.get(row["evidence_id"])
        corrected = bool(clock and clock.method in {"anchor_vote", "anchor_pair"} and abs(clock.offset_s) > 30)
        items.append(
            {
                "obs_id": obs_id,
                "t": float(row["t"]),
                "t_raw": float(row["t_raw"]) if not pd.isna(row["t_raw"]) else None,
                "sigma": float(row["sigma_t"]),
                "kind": row["kind"],
                "title": KIND_TITLES.get(row["kind"], row["kind"]),
                "summary": _summary(analysis, obs_id),
                "evidence_id": row["evidence_id"],
                "source": row["source"],
                "source_label": colmap(row["source"]).get("label", row["source"]),
                "phase": phase,
                "phase_label": phase_labels.get(phase, "Context"),
                "corrected": corrected,
                "offset_s": clock.offset_s if clock else 0.0,
            }
        )
    items.sort(key=lambda item: (item["t"], item["obs_id"]))
    core_times = [item["t"] for item in items if item["phase"] != "context"]
    window = None
    if core_times:
        lo, hi = min(core_times), max(core_times)
        items = [
            item for item in items if item["phase"] != "context" or lo - CONTEXT_BEFORE_S <= item["t"] <= hi + CONTEXT_AFTER_S
        ]
        pad = max((hi - lo) * 0.04, 1800.0)
        window = [lo - pad, hi + pad]
    elif items:
        window = [items[0]["t"] - 1800.0, items[-1]["t"] + 1800.0]
    if len(items) > 400:
        core = [i for i in items if i["phase"] != "context"]
        rest = [i for i in items if i["phase"] == "context"][: max(0, 400 - len(core))]
        items = sorted(core + rest, key=lambda item: (item["t"], item["obs_id"]))
    groups = [{"id": name, "label": label} for name, label in phase_labels.items()] + [{"id": "context", "label": "Context"}]
    return {"items": items, "groups": groups, "window": window}


def _graph_entities(analysis: Analysis) -> set[str]:
    view = analysis.view
    chosen: set[str] = set()
    for person_id in interesting_persons(analysis):
        chosen |= set(view.person(person_id).members)
    chosen |= set(analysis.taint.accounts)
    chosen |= set(analysis.seeds)
    for flow in analysis.taint.flows:
        if flow.get("atm"):
            chosen.add(flow["atm"])
    for link in analysis.links:
        if link.type == "same_actor" and link.extra.get("basis") == "infrastructure":
            chosen.add(f"domain:{link.extra['domain']}")
    return chosen


def build_graph(analysis: Analysis, hypothesis: dict[str, Any] | None) -> dict[str, Any]:
    view = analysis.view
    chosen = _graph_entities(analysis)
    role_of: dict[str, list[str]] = defaultdict(list)
    if hypothesis:
        for role in hypothesis.get("roles", []):
            for unit in role["units"]:
                for entity in view.members(unit):
                    role_of[entity].append(role["label"])
    nodes = []
    parents = set()
    for entity in sorted(chosen):
        person = view.entity_person.get(entity)
        indicators = sorted(view.indicators.of({entity}))
        node = {
            "id": entity,
            "label": display(entity),
            "kind": kind_of(entity),
            "kind_label": DISPLAY_NAMES.get(kind_of(entity), kind_of(entity)),
            "indicators": indicators,
            "roles": role_of.get(entity, []),
            "seed": entity in analysis.seeds,
        }
        if person and len(view.person(person).members) > 1:
            node["parent"] = person
            parents.add(person)
        nodes.append(node)
    for person_id in sorted(parents):
        person = view.person(person_id)
        roles = sorted({r for e in person.members for r in role_of.get(e, [])})
        nodes.append(
            {
                "id": person_id,
                "label": f"{person_id} {person.names[0] if person.names else person.label}",
                "kind": "person",
                "kind_label": "Person (inferred)",
                "roles": roles,
                "is_person": True,
                "seed": person.is_seed,
            }
        )
    edges = []
    facts = analysis.facts.edges
    if not facts.empty:
        subset = facts[facts["src"].isin(chosen) & facts["dst"].isin(chosen) & facts["kind"].isin(OBSERVED_GRAPH_KINDS)]
        for (src, dst, kind), group in subset.groupby(["src", "dst", "kind"]):
            amount = float(group["amount"].fillna(0).sum())
            label = kind.replace("_", " ")
            if amount:
                label = f"{label} Rs {amount:,.0f}"
            elif len(group) > 1:
                label = f"{label} x{len(group)}"
            edges.append(
                {
                    "id": f"F:{src}:{dst}:{kind}",
                    "source": src,
                    "target": dst,
                    "kind": kind,
                    "layer": "observed",
                    "label": label,
                    "count": len(group),
                    "amount": amount,
                    "obs": group["obs_id"].tolist()[:20],
                }
            )
    for link in analysis.links:
        if (
            link.type == "same_actor"
            and link.status != "observed"
            and link.a in chosen
            and link.b in chosen
            and link.status != "weak"
        ):
            edges.append(_link_edge(link, link.a, link.b))
        elif (
            link.type in {"co_presence", "impossibility"}
            and link.a in chosen
            and link.status in {"inferred", "confirmed", "rejected"}
        ):
            atm = link.extra.get("atm")
            target = atm if atm else None
            if target is None:
                account = link.extra.get("account")
                target = account
            if target and target in chosen:
                edges.append(_link_edge(link, link.a, target))
    unique = {}
    for edge in edges:
        key = (edge["source"], edge["target"], edge.get("link_type", edge["kind"]))
        if key not in unique or edge.get("w", 0) > unique[key].get("w", 0):
            unique[key] = edge
    return {"nodes": nodes, "edges": list(unique.values())}


def _link_edge(link, source: str, target: str) -> dict[str, Any]:
    layer = {"confirmed": "confirmed", "rejected": "rejected", "candidate": "candidate"}.get(link.status, "inferred")
    labels = {"same_actor": "same person", "co_presence": "present at withdrawal", "impossibility": "could not be there"}
    return {
        "id": link.link_id,
        "source": source,
        "target": target,
        "kind": link.type,
        "link_type": link.type,
        "layer": layer,
        "label": f"{labels.get(link.type, link.type)} (W {link.w:.1f})",
        "w": round(link.w, 2),
        "link_id": link.link_id,
        "verbal": verbal(link.w_calibrated),
    }


def build_map(analysis: Analysis, hypothesis: dict[str, Any] | None) -> dict[str, Any]:
    obs = analysis.obs
    points: list[dict[str, Any]] = []
    circles: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_point(obs_id: str, category: str, label: str) -> dict[str, Any] | None:
        if obs_id in seen or obs_id not in obs.index:
            return None
        row = obs.loc[obs_id]
        if pd.isna(row["lat"]):
            return None
        seen.add(obs_id)
        point = {
            "obs_id": obs_id,
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "radius_m": _num(row["radius_m"]) or 30.0,
            "category": category,
            "label": label,
            "t": None if pd.isna(row["t"]) else float(row["t"]),
            "time": fmt_ist(row["t"]) if not pd.isna(row["t"]) else "",
        }
        points.append(point)
        return point

    for flow in analysis.taint.flows:
        if flow["kind"] == "cash":
            for obs_id in flow["obs_ids"]:
                for link in analysis.links:
                    if link.type == "same_event" and obs_id in link.basis and link.extra.get("family") == "atm":
                        other = link.b if link.a == obs_id else link.a
                        add_point(other, "cash", f"Rs {flow['amount']:,.0f} withdrawn")
    for link in analysis.links:
        if link.type == "co_presence" and link.status in {"inferred", "confirmed"}:
            presence = link.basis[0]
            event = link.basis[1]
            row = obs.loc[presence]
            category = "cloud" if row["source"] == "cloud_location" else "presence"
            point = add_point(presence, category, f"{display(link.a)} ({KIND_TITLES.get(row['kind'], row['kind'])})")
            add_point(event, "cash", "Withdrawal")
            if event in obs.index and not pd.isna(row["lat"]):
                lines.append(
                    {
                        "from": [float(row["lat"]), float(row["lon"])],
                        "to": [float(obs.at[event, "lat"]), float(obs.at[event, "lon"])],
                        "kind": "co_presence",
                        "link_id": link.link_id,
                        "w": round(link.w, 2),
                    }
                )
            if point and category == "presence":
                circles.append({"lat": point["lat"], "lon": point["lon"], "radius_m": point["radius_m"], "label": row["place"]})
        elif link.type == "impossibility" and link.status in {"inferred", "confirmed"}:
            presence, event = link.basis[0], link.basis[1]
            point = add_point(presence, "cleared", f"{display(link.a)} elsewhere")
            if point and event in obs.index:
                lines.append(
                    {
                        "from": [point["lat"], point["lon"]],
                        "to": [float(obs.at[event, "lat"]), float(obs.at[event, "lon"])],
                        "kind": "impossibility",
                        "link_id": link.link_id,
                        "w": round(link.w, 2),
                    }
                )
    for obs_id in obs[obs["kind"] == "seizure"].index:
        add_point(obs_id, "seizure", f"Search premises: {obs.at[obs_id, 'attrs'].get('item_type', '')}")
    unique_circles = {(round(c["lat"], 5), round(c["lon"], 5)): c for c in circles}
    focus = [p for p in points if p["category"] != "cleared"] or points
    return {
        "points": points,
        "circles": list(unique_circles.values()),
        "lines": lines,
        "bounds": _bounds(focus),
        "full_bounds": _bounds(points),
    }


def _bounds(points: list[dict[str, Any]]) -> list[list[float]] | None:
    if not points:
        return None
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]
