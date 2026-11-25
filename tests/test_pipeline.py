from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sakshya.core.hashing import load_json
from sakshya.evaluation.metrics import clock_errors, money_scores, role_scores, tamper_scores, traceability
from sakshya.pipeline import Analysis, analyse, bundle

from .conftest import DEMO_IDS


def _truth(analysis: Analysis) -> dict:
    return load_json(analysis.case_dir / "truth.json")


@pytest.mark.parametrize("case_id", DEMO_IDS)
def test_offence_type_matches_the_answer_key(analyses: dict[str, Analysis], case_id: str) -> None:
    analysis = analyses[case_id]
    assert analysis.explained["decision"]["label"] == _truth(analysis)["class"]


@pytest.mark.parametrize("case_id", DEMO_IDS)
def test_clock_offsets_are_recovered(analyses: dict[str, Analysis], case_id: str) -> None:
    for row in clock_errors(analyses[case_id], _truth(analyses[case_id])):
        assert row["error_s"] < 60, row
        if row["kind"] == "timezone":
            assert row["detected_timezone"], row


@pytest.mark.parametrize("case_id", DEMO_IDS)
def test_money_trail_and_roles(analyses: dict[str, Analysis], case_id: str) -> None:
    analysis = analyses[case_id]
    truth = _truth(analysis)
    money = money_scores(analysis, truth)
    if truth["money"].get("tainted_accounts"):
        assert money["precision"] == 1.0 and money["recall"] == 1.0
    if money["cash_error_share"] is not None:
        assert money["cash_error_share"] < 0.05
    roles = role_scores(analysis, truth)
    if "mule_l1_correct" in roles:
        assert roles["mule_l1_correct"]


@pytest.mark.parametrize("case_id", DEMO_IDS)
def test_every_finding_points_to_hashed_evidence(analyses: dict[str, Analysis], case_id: str) -> None:
    analysis = analyses[case_id]
    result = traceability(analysis, bundle(analysis))
    assert result["share"] == 1.0
    assert tamper_scores(analysis, _truth(analysis))["false_alarms"] == 0


def test_tampered_frame_is_flagged(analyses: dict[str, Analysis]) -> None:
    caught = sum(tamper_scores(a, _truth(a))["caught"] for a in analyses.values())
    expected = sum(tamper_scores(a, _truth(a))["expected"] for a in analyses.values())
    assert expected > 0 and caught == expected


def test_decoys_with_common_names_are_not_merged(analyses: dict[str, Analysis]) -> None:
    for analysis in analyses.values():
        for pair in _truth(analysis).get("decoy_pairs", []):
            people = {analysis.view.entity_person.get(entity) for entity in pair}
            assert len(people) == 2 or None in people, pair


def test_same_input_gives_identical_output(demo_copy: Path, analyses: dict[str, Analysis]) -> None:
    case_id = DEMO_IDS[0]
    first = bundle(analyses[case_id])["digest"]
    again = bundle(analyse(demo_copy / case_id, record=False))["digest"]
    assert first == again


def test_bundle_is_complete_for_the_workbench(analyses: dict[str, Analysis]) -> None:
    data = bundle(analyses[DEMO_IDS[0]])
    for key in ("case", "decision", "hypotheses", "people", "links", "timeline", "graph", "map", "reach", "leads", "evidence"):
        assert key in data
    assert data["evidence"]["ledger"]["ok"]


def test_output_does_not_depend_on_hash_seed(demo_copy: Path) -> None:
    script = (
        "import sys; from pathlib import Path; from sakshya.pipeline import analyse, bundle; "
        "print(bundle(analyse(Path(sys.argv[1]), record=False))['digest'])"
    )
    root = Path(__file__).resolve().parent.parent
    digests = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
        result = subprocess.run(
            [sys.executable, "-c", script, str(demo_copy / DEMO_IDS[0])], env=env, capture_output=True, text=True, check=True
        )
        digests.add(result.stdout.strip())
    assert len(digests) == 1
