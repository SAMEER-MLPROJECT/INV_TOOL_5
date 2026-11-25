from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sakshya.generator.scenarios import (
    UpiParams,
    build_benign,
    build_sextortion,
    build_sim_swap,
    build_unknown,
    build_upi,
)
from sakshya.generator.world import World
from sakshya.generator.writer import CaseWriter

KINDS = ("upi_investment_fraud", "sextortion", "sim_swap_takeover", "no_offence", "unknown")

TITLES = {
    "upi_investment_fraud": "Fake trading app investment fraud",
    "sextortion": "Video call sextortion with UPI payments",
    "sim_swap_takeover": "SIM swap and unauthorised bank debits",
    "no_offence": "Furniture delivery dispute",
    "unknown": "Data theft with ransom demand",
}


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    kind: str
    seed: int
    scale: float = 1.0
    fixed: bool = False
    variant: str = "default"


def upi_params(seed: int, fixed: bool, variant: str) -> UpiParams:
    if fixed:
        return UpiParams(fixed=True)
    world_rng = World(seed).rng
    return UpiParams(
        fixed=False,
        n_payments=world_rng.randint(2, 4),
        n_l2=world_rng.randint(1, 3),
        decoys=world_rng.random() < 0.8,
        utc_export=world_rng.random() < 0.6,
        dvr_offset_s=world_rng.choice([-1, 1]) * world_rng.uniform(150, 660),
        background=world_rng.randint(240, 420),
        network=variant != "no_network" and world_rng.random() < 0.8,
        cloud=world_rng.random() < 0.7,
    )


def generate_case(spec: CaseSpec, out_root: Path) -> Path:
    out_dir = out_root / spec.case_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    world = World(spec.seed, scale=spec.scale)
    title = TITLES[spec.kind]
    writer = CaseWriter(spec.case_id, title)
    if spec.kind == "upi_investment_fraud":
        build_upi(world, writer, upi_params(spec.seed, spec.fixed, spec.variant))
    elif spec.kind == "sextortion":
        build_sextortion(world, writer)
    elif spec.kind == "sim_swap_takeover":
        build_sim_swap(world, writer)
    elif spec.kind == "no_offence":
        build_benign(world, writer)
    elif spec.kind == "unknown":
        build_unknown(world, writer)
    else:
        raise ValueError(f"Unknown case kind '{spec.kind}'")
    writer.truth.setdefault("generator", {})
    writer.truth["generator"] = {"kind": spec.kind, "seed": spec.seed, "scale": spec.scale, "fixed": spec.fixed}
    return writer.write(out_dir)


DEMO_CASES = [
    CaseSpec("CASE-2611-0147", "upi_investment_fraud", 7, fixed=True),
    CaseSpec("CASE-2611-0152", "sextortion", 31),
    CaseSpec("CASE-2611-0158", "sim_swap_takeover", 47),
    CaseSpec("CASE-2611-0163", "no_offence", 59),
    CaseSpec("CASE-2611-0171", "unknown", 83),
]


def heldout_specs(count_per_kind: int = 6, start_seed: int = 1000) -> list[CaseSpec]:
    specs = []
    seed = start_seed
    for kind in KINDS:
        for index in range(count_per_kind):
            specs.append(CaseSpec(f"HELD-{kind[:4].upper()}-{index + 1:02d}", kind, seed))
            seed += 1
    return specs


def training_specs(count: int = 8, start_seed: int = 500) -> list[CaseSpec]:
    return [CaseSpec(f"TRAIN-UPI-{i + 1:02d}", "upi_investment_fraud", start_seed + i) for i in range(count)]
