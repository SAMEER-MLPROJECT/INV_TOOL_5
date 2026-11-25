from __future__ import annotations

from collections import defaultdict

from sakshya.core.identifiers import PERSON_TYPES, display, kind_of
from sakshya.model import Link, Person
from sakshya.normalise.facts import EntityInfo

KIND_ORDER = ["phone", "account", "upi", "email", "cloud", "imsi", "imei", "mac", "host"]


class UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {i: i for i in items}
        self.members = {i: {i} for i in items}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> str:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        return ra


def cluster(
    entities: dict[str, EntityInfo],
    links: list[Link],
    seeds: list[str],
    merge_w: float,
    forbidden: set[frozenset[str]],
    distance: dict[str, int] | None = None,
) -> tuple[list[Person], dict[str, str], list[dict]]:
    node_set = {e for e, info in entities.items() if info.kind in PERSON_TYPES and info.case_relevant}
    for link in links:
        if link.type == "same_actor" and link.status in {"observed", "inferred", "confirmed"}:
            for end in (link.a, link.b):
                if kind_of(end) in PERSON_TYPES:
                    node_set.add(end)
    nodes = sorted(node_set)
    uf = UnionFind(nodes)
    via: dict[str, str] = {}
    score: dict[str, float] = {}
    blocked: list[dict] = []
    seed_set = set(seeds)
    usable = [
        l
        for l in links
        if l.type == "same_actor"
        and l.a in uf.parent
        and l.b in uf.parent
        and (l.status in {"observed", "confirmed"} or (l.status == "inferred" and l.w >= merge_w))
    ]
    usable.sort(key=lambda l: (0 if l.status in {"observed", "confirmed"} else 1, -l.w, l.link_id))
    for link in usable:
        ra, rb = uf.find(link.a), uf.find(link.b)
        if ra == rb:
            continue
        group_a, group_b = uf.members[ra], uf.members[rb]
        clash = next((pair for pair in forbidden if (pair & group_a) and (pair & group_b)), None) if forbidden else None
        if clash is not None:
            blocked.append({"link_id": link.link_id, "reason": "Merge would join identifiers marked as different people"})
            continue
        if (
            (group_a & seed_set or group_b & seed_set)
            and link.status == "inferred"
            and link.extra.get("basis") == "shared_handset"
        ):
            blocked.append(
                {"link_id": link.link_id, "reason": "Shared handset does not attach new identifiers to the complainant"}
            )
            continue
        uf.union(link.a, link.b)
        for end in (link.a, link.b):
            if end not in via:
                via[end] = link.link_id
                score[end] = link.w
    groups = defaultdict(list)
    for node in nodes:
        groups[uf.find(node)].append(node)
    persons: list[Person] = []
    for members in groups.values():
        members.sort(key=lambda e: (KIND_ORDER.index(kind_of(e)) if kind_of(e) in KIND_ORDER else 99, e))
        names: list[str] = []
        for member in members:
            for name in entities.get(member).names if member in entities else []:
                if name not in names:
                    names.append(name)
        is_seed = bool(set(members) & seed_set)
        label = display(members[0])
        persons.append(
            Person(
                person_id="",
                members={m: round(score.get(m, 4.0), 3) for m in members},
                via={m: via[m] for m in members if m in via},
                names=names,
                label=label,
                is_seed=is_seed,
            )
        )
    reach = distance or {}
    persons.sort(key=lambda p: (not p.is_seed, min((reach.get(m, 99) for m in p.members), default=99), -len(p.members), p.label))
    entity_person: dict[str, str] = {}
    for index, person in enumerate(persons, start=1):
        person.person_id = f"P{index:02d}"
        for member in person.members:
            entity_person[member] = person.person_id
    return persons, entity_person, blocked
