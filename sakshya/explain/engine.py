from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from sakshya.core.config import config_file, settings, templates
from sakshya.indicators.compute import Indicator, IndicatorSet
from sakshya.model import Link, Person
from sakshya.money.flows import TaintResult
from sakshya.normalise.facts import Facts

COMM_KINDS = {"call", "chat", "sms", "email"}


@dataclass
class CaseView:
    obs: pd.DataFrame
    facts: Facts
    links: list[Link]
    persons: list[Person]
    entity_person: dict[str, str]
    indicators: IndicatorSet
    taint: TaintResult
    seeds: list[str]
    evidence_subjects: dict[str, list[str]]
    evidence_sources: dict[str, str]

    def person(self, person_id: str) -> Person:
        return next(p for p in self.persons if p.person_id == person_id)

    def members(self, unit: str) -> set[str]:
        if unit.startswith("P") and unit[1:].isdigit():
            return set(self.person(unit).members)
        return {unit}

    def seed_person(self) -> str | None:
        for seed in self.seeds:
            if seed in self.entity_person:
                return self.entity_person[seed]
        return None


def _role_score(
    view: CaseView, role: dict[str, Any], units: list[str], extra: dict[str, Indicator] | None = None
) -> tuple[float, list[dict]]:
    entities: set[str] = set()
    for unit in units:
        entities |= view.members(unit)
    found = view.indicators.of(entities)
    if extra:
        found.update(extra)
    items = []
    total = 0.0
    for name in role.get("supports", []):
        if name in found:
            w = abs(found[name].weight)
            total += w
            items.append(
                {
                    "kind": "indicator",
                    "role": role["name"],
                    "name": name,
                    "w": w,
                    "detail": found[name].detail,
                    "evidence": found[name].evidence,
                    "entity": found[name].entity,
                }
            )
    for name in role.get("contradicts", []):
        if name in found:
            w = -abs(found[name].weight)
            total += w
            items.append(
                {
                    "kind": "indicator",
                    "role": role["name"],
                    "name": name,
                    "w": w,
                    "detail": found[name].detail,
                    "evidence": found[name].evidence,
                    "entity": found[name].entity,
                }
            )
    return total, items


def _comm_obs(view: CaseView, a: set[str], b: set[str]) -> list[str]:
    edges = view.facts.edges
    if edges.empty:
        return []
    mask = edges["kind"].isin({"called", "texted", "messaged", "emailed"}) & (
        (edges["src"].isin(a) & edges["dst"].isin(b)) | (edges["src"].isin(b) & edges["dst"].isin(a))
    )
    return sorted(set(edges[mask]["obs_id"]))


def find_candidates(view: CaseView, finder: str, binding: dict[str, list[str]]) -> list[str]:
    seed_person = view.seed_person()
    seed_entities = view.members(seed_person) if seed_person else set(view.seeds)
    if finder == "seed":
        return [seed_person] if seed_person else []
    if finder == "contacted_seed":
        edges = view.facts.edges
        if edges.empty:
            return []
        comm = edges[edges["kind"].isin({"called", "texted", "messaged", "emailed"})]
        others = set(comm[comm["src"].isin(seed_entities)]["dst"]) | set(comm[comm["dst"].isin(seed_entities)]["src"])
        persons = {view.entity_person[e] for e in others if e in view.entity_person and view.entity_person[e] != seed_person}
        return sorted(persons)
    if finder == "first_hop_accounts":
        return sorted({f["dst"] for f in view.taint.flows if f["origin"] and f["dst"]})
    if finder == "onward_accounts":
        first = set(binding.get("mule_l1", []))
        found = set()
        frontier = set(first)
        for _ in range(3):
            nxt = {
                f["dst"] for f in view.taint.flows if f["src"] in frontier and f["dst"] and not str(f["dst"]).startswith("cash")
            }
            nxt -= first | found
            found |= nxt
            frontier = nxt
        return sorted(found)
    if finder == "present_at_cash":
        accounts = set(binding.get("mule_l1", [])) | set(binding.get("mule_l2", []))
        persons = set()
        for link in view.links:
            if (
                link.type == "co_presence"
                and link.status in {"inferred", "confirmed"}
                and link.extra.get("account") in accounts
                and link.a in view.entity_person
            ):
                persons.add(view.entity_person[link.a])
        return sorted(persons)
    if finder == "device_operators":
        persons = set()
        for indicator in view.indicators.all():
            if indicator.name == "beaconing" and indicator.entity in view.entity_person:
                persons.add(view.entity_person[indicator.entity])
        return sorted(persons - {seed_person})
    if finder == "sim_controller":
        persons = set()
        for indicator in view.indicators.all():
            if indicator.name == "sim_takeover" and indicator.entity in view.entity_person:
                persons.add(view.entity_person[indicator.entity])
        return sorted(persons - {seed_person})
    return []


def _phase_events(view: CaseView, name: str, binding: dict[str, list[str]], role: str) -> list[str]:
    units = binding.get(role, [])
    entities: set[str] = set()
    for unit in units:
        entities |= view.members(unit)
    seed_person = view.seed_person()
    seed_entities = view.members(seed_person) if seed_person else set(view.seeds)
    if name == "contact":
        return _comm_obs(view, entities, seed_entities)
    if name in {"lure", "threat"}:
        indicator = "lure_language" if name == "lure" else "threat_language"
        found = view.indicators.of(entities)
        return list(found[indicator].evidence) if indicator in found else []
    if name == "payment":
        return [f["obs_ids"][0] for f in view.taint.flows if f["origin"] and f["dst"] in entities]
    if name == "layering":
        return [f["obs_ids"][0] for f in view.taint.flows if f["src"] in entities and f["kind"] != "cash"]
    if name == "cash_out":
        accounts = entities | {a for u in binding.get("mule_l1", []) for a in view.members(u)}
        return [f["obs_ids"][0] for f in view.taint.flows if f["src"] in accounts and f["kind"] == "cash"]
    if name == "control":
        found = view.indicators.of(entities)
        return list(found["beaconing"].evidence) if "beaconing" in found else []
    if name == "sim_change":
        found = view.indicators.of(entities)
        return list(found["sim_takeover"].evidence) if "sim_takeover" in found else []
    if name == "otp":
        found = view.indicators.of(entities)
        return list(found["otp_on_new_sim"].evidence) if "otp_on_new_sim" in found else []
    return []


def _observability(view: CaseView, rules: list[dict[str, Any]], binding: dict[str, list[str]]) -> float:
    miss = 1.0
    for rule in rules:
        sources = [e for e, s in view.evidence_sources.items() if s == rule["source"]]
        if not sources:
            continue
        if rule.get("of"):
            entities: set[str] = set()
            for unit in binding.get(rule["of"], []):
                entities |= view.members(unit)
            if not entities or not any(set(view.evidence_subjects.get(e, [])) & entities for e in sources):
                continue
        miss *= 1.0 - float(rule["o"])
    return 1.0 - miss


def _times(view: CaseView, obs_ids: list[str]) -> list[float]:
    values = []
    for obs_id in obs_ids:
        if obs_id in view.obs.index:
            t = view.obs.at[obs_id, "t"]
            if not pd.isna(t):
                values.append(float(t))
    return sorted(values)


def _contact_with_suspects(
    view: CaseView, binding: dict[str, list[str]], role: str, partner_roles: list[str]
) -> dict[str, Indicator]:
    accounts = [a for u in binding.get(role, []) for a in view.members(u)]
    phones = {view.facts.registered_phone.get(a) for a in accounts} - {None}
    partners: set[str] = set()
    for partner in partner_roles:
        for unit in binding.get(partner, []):
            partners |= view.members(unit)
    obs_ids = _comm_obs(view, phones, partners) if phones and partners else []
    if not obs_ids:
        return {}
    weight = config_file("indicators.yaml")["weights"]["contact_with_suspects"]
    return {
        "contact_with_suspects": Indicator(
            "contact_with_suspects",
            next(iter(phones)),
            weight,
            len(obs_ids),
            obs_ids[:4],
            f"Registered phone of the account was in contact with the suspect {len(obs_ids)} times",
        )
    }


def evaluate(view: CaseView, template: dict[str, Any], binding: dict[str, list[str]], variant: dict[str, str]) -> dict[str, Any]:
    cfg = settings()["explain"]
    breakdown: list[dict[str, Any]] = [{"kind": "prior", "label": "Prior for this kind of offence", "w": template["prior_log10"]}]
    roles_out = []
    links_used: list[str] = []
    partner_roles = [r["name"] for r in template["roles"] if r.get("find") in {"contacted_seed", "sim_controller"}]
    for role in template["roles"]:
        units = binding.get(role["name"], [])
        extra = _contact_with_suspects(view, binding, role["name"], partner_roles) if role.get("variants") else {}
        score, items = _role_score(view, role, units, extra)
        chosen = variant.get(role["name"])
        if chosen:
            spec = role["variants"][chosen]
            vscore, vitems = _role_score(
                view,
                {"name": role["name"], "supports": spec.get("supports", []), "contradicts": spec.get("contradicts", [])},
                units,
                extra,
            )
            score += vscore
            for item in vitems:
                item["variant"] = chosen
            items += vitems
        breakdown += items
        if role["name"] == "cashout" and units:
            entities = set().union(*(view.members(u) for u in units))
            accounts = {a for r in ("mule_l1", "mule_l2") for u in binding.get(r, []) for a in view.members(u)}
            best = None
            for link in view.links:
                if (
                    link.type == "co_presence"
                    and link.a in entities
                    and link.status in {"inferred", "confirmed"}
                    and link.extra.get("account") in accounts
                    and (best is None or link.w > best.w)
                ):
                    best = link
            if best is not None:
                breakdown.append(
                    {
                        "kind": "link",
                        "role": "cashout",
                        "label": "Strongest presence at a cash withdrawal",
                        "w": round(best.w, 3),
                        "link_id": best.link_id,
                        "detail": best.claim,
                    }
                )
                links_used.append(best.link_id)
        roles_out.append(
            {
                "name": role["name"],
                "label": role["label"],
                "units": units,
                "score": round(score, 3),
                "variant": role["variants"][chosen]["label"] if chosen else None,
                "optional": bool(role.get("optional")),
            }
        )
    phases_out = []
    times: dict[str, float] = {}
    for phase in template["phases"]:
        events = _phase_events(view, phase["events"], binding, phase["role"])
        stamps = _times(view, events)
        o = _observability(view, phase.get("observability", []), binding)
        entry = {
            "name": phase["name"],
            "label": phase["label"],
            "role": phase["role"],
            "events": events[:40],
            "times": stamps[:60],
            "event_count": len(events),
            "t_first": stamps[0] if stamps else None,
            "t_last": stamps[-1] if stamps else None,
            "observability": round(o, 3),
            "filled": bool(events),
            "order_ok": True,
            "penalty": 0.0,
            "optional": bool(phase.get("optional")),
        }
        if events:
            times[phase["name"]] = stamps[0] if stamps else None
            after = phase.get("after")
            if after and times.get(after) is not None and stamps:
                gap = stamps[0] - times[after]
                if gap < -3600:
                    entry["order_ok"] = False
                    entry["penalty"] = cfg["order_penalty"]
                    breakdown.append(
                        {
                            "kind": "order",
                            "label": f"{phase['label']} happens before {after.replace('_', ' ')}",
                            "w": cfg["order_penalty"],
                            "phase": phase["name"],
                        }
                    )
                elif phase.get("max_lag_h") and gap > phase["max_lag_h"] * 3600:
                    entry["order_ok"] = False
                    entry["penalty"] = cfg["order_penalty"] / 2
                    breakdown.append(
                        {
                            "kind": "order",
                            "label": f"{phase['label']} came {gap / 3600:.0f} h after {after.replace('_', ' ')}, "
                            f"later than the usual {phase['max_lag_h']} h",
                            "w": cfg["order_penalty"] / 2,
                            "phase": phase["name"],
                        }
                    )
        elif not phase.get("optional"):
            penalty = math.log10(max(1e-3, 1.0 - o))
            entry["penalty"] = round(penalty, 3)
            if penalty < 0:
                breakdown.append(
                    {
                        "kind": "missing",
                        "label": f"No {phase['label'].lower()} found although the evidence would show it (observability {o:.0%})",
                        "w": round(penalty, 3),
                        "phase": phase["name"],
                    }
                )
        phases_out.append(entry)
    score = sum(item["w"] for item in breakdown)
    gaps = [p["name"] for p in phases_out if not p["filled"] and not p["optional"]]
    unbound = [r["name"] for r in roles_out if not r["units"] and not r["optional"]]
    return {
        "template": template["class"],
        "label": template["label"],
        "score": round(score, 3),
        "roles": roles_out,
        "phases": phases_out,
        "breakdown": breakdown,
        "gaps": gaps,
        "unbound": unbound,
        "links_used": links_used,
        "variant": {k: template_role(template, k)["variants"][v]["label"] for k, v in variant.items()},
    }


def template_role(template: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in template["roles"] if r["name"] == name)


def search(view: CaseView, template: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = settings()["explain"]
    beam: list[tuple[float, dict[str, list[str]]]] = [(0.0, {})]
    for role in template["roles"]:
        expanded: list[tuple[float, dict[str, list[str]]]] = []
        for partial_score, binding in beam:
            candidates = find_candidates(view, role["find"], binding)
            if role.get("kind") == "account" or role.get("set"):
                scored = [(c, _role_score(view, role, [c])[0]) for c in candidates]
                chosen = [c for c, s in scored if s >= 0] or (
                    [c for c, _ in scored] if role.get("kind") == "account" and not role.get("optional") else []
                )
                score = _role_score(view, role, chosen)[0] if chosen else 0.0
                expanded.append((partial_score + score, {**binding, role["name"]: chosen}))
                continue
            scored = sorted(((c, _role_score(view, role, [c])[0]) for c in candidates), key=lambda item: (-item[1], item[0]))
            options = scored[: cfg["branch"]]
            for candidate, score in options:
                expanded.append((partial_score + score, {**binding, role["name"]: [candidate]}))
            if not options or role.get("optional"):
                expanded.append((partial_score, {**binding, role["name"]: []}))
        expanded.sort(key=lambda item: -item[0])
        beam = expanded[: cfg["beam_width"]]
    results = []
    seen = set()
    for _, binding in beam:
        key = tuple((k, tuple(v)) for k, v in sorted(binding.items()))
        if key in seen:
            continue
        seen.add(key)
        variant_roles = [r for r in template["roles"] if r.get("variants") and binding.get(r["name"])]
        variants: list[dict[str, str]] = [{}]
        for role in variant_roles:
            variants = [{**v, role["name"]: name} for v in variants for name in role["variants"]]
        for variant in variants:
            hypothesis = evaluate(view, template, binding, variant)
            hypothesis["binding"] = binding
            results.append(hypothesis)
    results.sort(key=lambda h: -h["score"])
    return results


def explain(view: CaseView) -> dict[str, Any]:
    cfg = settings()["explain"]
    weights = config_file("indicators.yaml")
    hypotheses: list[dict[str, Any]] = []
    for template in templates():
        hypotheses += search(view, template)[:4]
    hypotheses.sort(key=lambda h: -h["score"])
    best_by_class: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        best_by_class.setdefault(hypothesis["template"], hypothesis)
    baseline = {
        "template": "no_offence",
        "label": "No offence",
        "score": 0.0,
        "roles": [],
        "phases": [],
        "breakdown": [{"kind": "baseline", "label": "Reference: every event explained by ordinary activity", "w": 0.0}],
        "gaps": [],
        "unbound": [],
        "links_used": [],
        "variant": {},
        "binding": {},
    }
    ranked = [*hypotheses[:8], baseline]
    ranked.sort(key=lambda h: -h["score"])
    for index, hypothesis in enumerate(ranked, start=1):
        hypothesis["rank"] = index
        hypothesis["id"] = f"H{index}"
        nxt = ranked[index] if index < len(ranked) else None
        hypothesis["margin_next"] = round(hypothesis["score"] - nxt["score"], 3) if nxt else None
    suspicious = [i for i in view.indicators.all() if i.name in weights["suspicious"] and i.weight >= cfg["suspicious_floor"]]
    classes = sorted(best_by_class.values(), key=lambda h: -h["score"])
    top = classes[0] if classes else None
    runner = max([h["score"] for h in classes[1:]] + [0.0]) if top else 0.0
    if top and top["score"] >= cfg["tau"] and top["score"] - runner >= cfg["margin"]:
        factor = 10 ** (top["score"] - runner)
        decision = {
            "label": top["template"],
            "title": top["label"],
            "score": top["score"],
            "margin": round(top["score"] - runner, 3),
            "reason": f"{top['label']} explains the evidence {factor:,.0f} times better than the next explanation",
        }
    elif suspicious:
        decision = {
            "label": "unknown",
            "title": "Unknown pattern",
            "score": top["score"] if top else 0.0,
            "margin": round((top["score"] - runner) if top else 0.0, 3),
            "reason": "Suspicious activity is present but no known offence pattern fits clearly enough",
        }
    else:
        decision = {
            "label": "no_offence",
            "title": "No offence indicated",
            "score": top["score"] if top else 0.0,
            "margin": round((top["score"] - runner) if top else 0.0, 3),
            "reason": "No suspicious indicators and no offence pattern scores above ordinary activity",
        }
    decision["suspicious"] = [{"name": i.name, "entity": i.entity, "detail": i.detail} for i in suspicious[:10]]
    return {"decision": decision, "hypotheses": ranked}
