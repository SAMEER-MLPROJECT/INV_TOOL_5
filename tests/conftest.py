from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sakshya.pipeline import Analysis, analyse

DEMO = Path(__file__).resolve().parent.parent / "sakshya" / "data" / "demo_cases"
DEMO_IDS = sorted(p.name for p in DEMO.iterdir() if (p / "case.yaml").exists())


@pytest.fixture(scope="session")
def demo_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cases")
    for case_id in DEMO_IDS:
        shutil.copytree(DEMO / case_id, root / case_id)
    return root


@pytest.fixture(scope="session")
def analyses(demo_copy: Path) -> dict[str, Analysis]:
    return {case_id: analyse(demo_copy / case_id) for case_id in DEMO_IDS}
