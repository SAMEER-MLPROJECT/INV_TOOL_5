from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from sakshya import __version__
from sakshya.core.config import config_digest, settings
from sakshya.core.hashing import dump_json, load_json, sha256_json
from sakshya.custody.intake import Evidence, check_media, load_manifest, register_evidence
from sakshya.custody.ledger import Ledger
from sakshya.decide.leads import fragility, rank_leads
from sakshya.explain.engine import CaseView, explain
from sakshya.indicators.compute import attach_kyc_dates, compute
from sakshya.links.engine import build_context, cash_events, co_presence_links, same_actor_links, same_event_links
from sakshya.links.sequence import contact_payment_links, fit_beta, sequence_links
from sakshya.model import ClockEstimate, Link
from sakshya.money.flows import Statement, TaintResult, Transfer, build_transfers, suspicious_payments, trace
from sakshya.normalise.clock import apply_offsets, estimate_offsets
from sakshya.normalise.facts import Facts, build_facts, case_linked, seed_entities
from sakshya.normalise.ingest import ingest
from sakshya.people.cluster import cluster
from sakshya.predict.hmm import predict
from sakshya.reach.freeze import freeze_list
from sakshya.views import build_graph, build_map, build_people, build_timeline, summarise_links

ACTIONS_FILE = "actions.json"


@dataclass
class Analysis:
    case_dir: Path
    manifest: dict[str, Any]
    evidence: list[Evidence]
    obs: pd.DataFrame
    facts: Facts
    clocks: dict[str, ClockEstimate]
    links: list[Link]
    transfers: list[Transfer]
    books: dict[str, Statement]
    taint: TaintResult
    view: CaseView
    explained: dict[str, Any]
    seeds: list[str]
    reference_t: float | None
    media: list[dict[str, Any]]
    warnings: dict[str, list[str]]
    actions: list[dict[str, Any]]
    blocked_merges: list[dict[str, Any]]
    presence_scored: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return str(self.manifest["id"])

    def crime_hypothesis(self) -> dict[str, Any] | None:
        label = self.explained["decision"]["label"]
        for hypothesis in self.explained["hypotheses"]:
            if hypothesis["template"] == label:
                return hypothesis
        return next((h for h in self.explained["hypotheses"] if h["template"] != "no_offence"), None)

    def default_as_of(self) -> float:
        if self.reference_t is not None:
            return self.reference_t
        times = self.obs["t"].dropna()
        return float(times.max()) if not times.empty else time.time()

    def time_range(self) -> tuple[float, float]:
        hypothesis = self.crime_hypothesis()
        stamps = [t for p in (hypothesis or {}).get("phases", []) for t in p.get("times", [])]
        if not stamps:
            series = self.obs["t"].dropna()
            stamps = [float(series.min()), float(series.max())] if not series.empty else [0.0, 0.0]
        return min(stamps), max(max(stamps), self.default_as_of())

    def money(self, as_of: float | None = None, policy: str | None = None) -> TaintResult:
        if as_of is None and (policy is None or policy == self.taint.policy):
            return self.taint
        return trace(
            self.transfers,
            self.books,
            [s for s in self.seeds if s.startswith("account:")],
            policy or settings()["money"]["default_policy"],
            as_of,
            settings()["money"]["new_payee_days"],
            self.reference_t,
        )

    def predict(self, as_of: float | None = None) -> dict[str, Any]:
        if self.explained["decision"]["label"] in {"unknown", "no_offence"}:
            return {"available": False, "reason": "No offence pattern was confirmed, so there is no trajectory to project"}
        return predict(self.crime_hypothesis(), as_of if as_of is not None else self.default_as_of())

    def reach(self, as_of: float | None = None, policy: str | None = None) -> dict[str, Any]:
        moment = as_of if as_of is not None else self.default_as_of()
        taint = self.money(moment, policy)
        prediction = self.predict(moment)
        return {
            "as_of": moment,
            "policy": taint.policy,
            "trace": taint.to_dict(),
            "freeze": freeze_list(taint, prediction, self.crime_hypothesis()),
            "prediction": prediction,
        }


def load_actions(case_dir: Path) -> list[dict[str, Any]]:
    path = case_dir / ACTIONS_FILE
    return load_json(path) if path.exists() else []


def _apply_actions(links: list[Link], actions: list[dict[str, Any]]) -> set[frozenset[str]]:
    by_id = {link.link_id: link for link in links}
    forbidden: set[frozenset[str]] = set()
    for action in actions:
        target = action.get("target")
        if action["type"] in {"reject_link", "confirm_link"} and target in by_id:
            link = by_id[target]
            if action["type"] == "reject_link":
                link.status = "rejected"
                if link.type == "same_actor":
                    forbidden.add(frozenset({link.a, link.b}))
            else:
                link.status = "confirmed"
            verdict = "Rejected" if action["type"] == "reject_link" else "Confirmed"
            link.note = f"{verdict} by investigator: {action.get('reason', '')}".strip()
        elif action["type"] == "forbid_merge" and isinstance(target, list) and len(target) == 2:
            forbidden.add(frozenset(target))
    return forbidden


def analyse(case_dir: Path, record: bool = True) -> Analysis:
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def mark(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[name] = round(now - clock, 4)
        clock = now

    cfg = settings()
    manifest = load_manifest(case_dir)
    ledger = Ledger(case_dir / "ledger.jsonl")
    evidence = register_evidence(case_dir, manifest, ledger)
    intake = ingest(case_dir, evidence)
    clocks = estimate_offsets(intake.obs, evidence)
    obs = apply_offsets(intake.obs, clocks)
    mark("intake_and_normalise")
    frames = {}
    for row in obs[obs["kind"] == "cctv_event"].itertuples(index=False):
        if row.attrs.get("frame_file"):
            frames[row.attrs["frame_file"]] = (row.attrs.get("frame_sha256", ""), row.obs_id)
    media = check_media(evidence, frames)
    facts = build_facts(obs, intake.ids)
    attach_kyc_dates(facts, obs)
    seeds = seed_entities(manifest, facts)
    linked = case_linked(facts, seeds, cfg["links"]["case_link_depth"])
    ctx = build_context(obs, facts, seeds, linked)
    mark("facts")
    same_event = same_event_links(ctx)
    events = cash_events(ctx, same_event)
    copresence, impossible, presence_scored = co_presence_links(ctx, events)
    same_actor = same_actor_links(ctx)
    complaints = ctx.obs[ctx.obs["kind"] == "complaint"]["t"].dropna()
    reference_t = float(complaints.min()) if not complaints.empty else None
    transfers, books = build_transfers(ctx.obs, facts)
    seed_accounts = [s for s in seeds if s.startswith("account:")]
    taint = trace(
        transfers, books, seed_accounts, cfg["money"]["default_policy"], None, cfg["money"]["new_payee_days"], reference_t
    )
    beta = fit_beta(transfers, books)
    sequence = sequence_links(transfers, books, ctx.obs, ctx.cfg, beta)
    origins = suspicious_payments(transfers, seed_accounts, cfg["money"]["new_payee_days"], reference_t)
    seed_out = [tr for tr in transfers if tr.src in seed_accounts]
    span = (max((tr.t for tr in seed_out), default=0) - min((tr.t for tr in seed_out), default=0)) / 86400.0
    background_per_day = len(seed_out) / max(span, 30.0)
    contact = contact_payment_links(origins, ctx.obs, facts.roles, seeds, ctx.cfg, background_per_day)
    links = same_event + copresence + impossible + same_actor + sequence + contact
    mark("links")
    actions = load_actions(case_dir)
    forbidden = _apply_actions(links, actions)
    persons, entity_person, blocked = cluster(facts.entities, links, seeds, cfg["links"]["merge_w"], forbidden, linked)
    indicators = compute(ctx.obs, facts, transfers, books, taint, links, seeds)
    subjects = {}
    for evidence_id, items in intake.subjects.items():
        subjects[evidence_id] = [f"{kind}:{value}" for kind, value in items]
    for item in evidence:
        if item.entry.get("account"):
            subjects.setdefault(item.evidence_id, []).append(f"account:{item.entry['account']}")
    view = CaseView(
        ctx.obs,
        facts,
        links,
        persons,
        entity_person,
        indicators,
        taint,
        seeds,
        subjects,
        {e.evidence_id: e.source for e in evidence},
    )
    mark("people_and_indicators")
    explained = explain(view)
    mark("explain")
    analysis = Analysis(
        case_dir,
        manifest,
        evidence,
        ctx.obs,
        facts,
        clocks,
        links,
        transfers,
        books,
        taint,
        view,
        explained,
        seeds,
        reference_t,
        media,
        intake.warnings,
        actions,
        blocked,
        presence_scored,
        timings,
    )
    if record:
        _record_run(analysis, ledger)
    return analysis


def bundle(analysis: Analysis) -> dict[str, Any]:
    started = time.perf_counter()
    explained = analysis.explained
    hypotheses = explained["hypotheses"]
    crime = analysis.crime_hypothesis()
    default_as_of = analysis.default_as_of()
    reach = analysis.reach(default_as_of)
    leads_input = _lead_context(analysis, hypotheses)
    people = build_people(analysis)
    data = {
        "case": {
            "id": analysis.case_id,
            "title": analysis.manifest.get("title", analysis.case_id),
            "seed": analysis.manifest.get("seed", {}),
            "seed_entities": analysis.seeds,
            "complaint_time": analysis.reference_t,
            "time_range": analysis.time_range(),
            "default_as_of": default_as_of,
            "engine_version": __version__,
        },
        "decision": explained["decision"],
        "hypotheses": [_public_hypothesis(analysis, h) for h in hypotheses],
        "people": people,
        "fragility": fragility(hypotheses),
        "leads": rank_leads(leads_input),
        "reach": reach,
        "links": summarise_links(analysis),
        "timeline": build_timeline(analysis, crime),
        "graph": build_graph(analysis, crime),
        "map": build_map(analysis, crime),
        "evidence": evidence_view(analysis),
        "actions": analysis.actions,
        "blocked_merges": analysis.blocked_merges,
        "counts": {
            "observations": len(analysis.obs),
            "evidence": len(analysis.evidence),
            "links": len(analysis.links),
            "persons": len(analysis.view.persons),
            "entities": len(analysis.facts.entities),
        },
    }
    data["digest"] = analysis_digest(data)
    analysis.timings["views"] = round(time.perf_counter() - started, 4)
    data["timings"] = analysis.timings
    return data


def _public_hypothesis(analysis: Analysis, hypothesis: dict[str, Any]) -> dict[str, Any]:
    view = analysis.view
    roles = []
    for role in hypothesis.get("roles", []):
        units = []
        for unit in role["units"]:
            if unit.startswith("P") and unit[1:].isdigit():
                person = view.person(unit)
                units.append(
                    {
                        "id": unit,
                        "kind": "person",
                        "label": person.label,
                        "names": person.names,
                        "identifiers": list(person.members)[:12],
                    }
                )
            else:
                person_id = view.entity_person.get(unit)
                units.append(
                    {
                        "id": unit,
                        "kind": "account",
                        "label": unit.split(":", 1)[1].replace(":", " "),
                        "person": person_id,
                        "names": view.person(person_id).names if person_id else [],
                    }
                )
        roles.append({**role, "units": units})
    phases = [{k: v for k, v in phase.items() if k != "times"} for phase in hypothesis.get("phases", [])]
    return {**{k: v for k, v in hypothesis.items() if k not in {"roles", "phases"}}, "roles": roles, "phases": phases}


def _lead_context(analysis: Analysis, hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    sources = {e.source for e in analysis.evidence}
    statement_accounts = set(analysis.books)
    cdr_phones = {
        s for e in analysis.evidence if e.source == "cdr" for s in analysis.view.evidence_subjects.get(e.evidence_id, [])
    }
    person_phones = {p.person_id: [m for m in p.members if m.startswith("phone:")] for p in analysis.view.persons}
    cash_atms = sorted({f["atm"] for f in analysis.taint.flows if f["kind"] == "cash" and f.get("atm")})
    cctv_atms = {f"atm:{e.entry.get('atm_id')}" for e in analysis.evidence if e.source == "cctv_log"}
    dump_atms = set()
    for e in analysis.evidence:
        if e.source == "tower_dump":
            for atm in cash_atms:
                if atm.split(":", 1)[1] in e.file:
                    dump_atms.add(atm)
    infrastructure = set()
    for link in analysis.links:
        if link.type == "same_actor" and link.extra.get("basis") == "infrastructure" and link.status != "rejected":
            infrastructure.add(f"domain:{link.extra['domain']}")
    return {
        "sources": sources,
        "statement_accounts": statement_accounts,
        "cdr_phones": cdr_phones,
        "person_phones": person_phones,
        "cash_atms": cash_atms,
        "cctv_atms": cctv_atms,
        "dump_atms": dump_atms,
        "infrastructure": sorted(infrastructure),
        "hypotheses": hypotheses,
        "tainted_accounts": sorted(a for a, info in analysis.taint.accounts.items() if info.tainted_in > 0),
        "held": {a: info.tainted_held for a, info in analysis.taint.accounts.items()},
    }


def evidence_view(analysis: Analysis) -> dict[str, Any]:
    items = []
    counts = analysis.obs.groupby("evidence_id").size().to_dict()
    for item in analysis.evidence:
        clock = analysis.clocks.get(item.evidence_id)
        items.append(
            {
                **item.to_dict(),
                "records": int(counts.get(item.evidence_id, 0)),
                "clock": clock.to_dict() if clock else None,
                "warnings": analysis.warnings.get(item.evidence_id, []),
            }
        )
    return {"items": items, "media": analysis.media, **ledger_view(analysis.case_dir)}


def analysis_digest(data: dict[str, Any]) -> str:
    content = {k: v for k, v in data.items() if k not in {"timings", "digest"}}
    content["evidence"] = {k: v for k, v in data["evidence"].items() if k not in {"ledger", "ledger_entries"}}
    return sha256_json(content)


def ledger_view(case_dir: Path) -> dict[str, Any]:
    ledger = Ledger(case_dir / "ledger.jsonl")
    return {"ledger": ledger.verify().to_dict(), "ledger_entries": ledger.entries()[-60:]}


def _record_run(analysis: Analysis, ledger: Ledger) -> None:
    configuration = config_digest()
    inputs = {
        "evidence": {e.evidence_id: e.sha256 for e in analysis.evidence},
        "actions": analysis.actions,
        "engine": __version__,
        "configuration": configuration,
    }
    digest = sha256_json(inputs)
    last = ledger.last("analysis")
    if last is None or last["payload"].get("inputs_sha256") != digest:
        ledger.append(
            "analysis",
            {
                "inputs_sha256": digest,
                "engine": __version__,
                "configuration_sha256": configuration,
                "decision": analysis.explained["decision"]["label"],
                "score": analysis.explained["decision"]["score"],
            },
        )


def save_bundle(case_dir: Path, data: dict[str, Any]) -> Path:
    path = case_dir / "analysis" / "bundle.json"
    dump_json(path, data)
    return path
