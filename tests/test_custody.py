from __future__ import annotations

import json
from pathlib import Path

from sakshya.custody.ledger import Ledger


def test_ledger_chain_verifies_and_detects_edits(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for index in range(4):
        ledger.append("note", {"index": index}, moment=1000.0 + index)
    check = ledger.verify()
    assert check.ok and check.entries == 4
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])
    entry["payload"]["index"] = 99
    lines[2] = json.dumps(entry, sort_keys=True)
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    broken = ledger.verify()
    assert not broken.ok
    assert broken.broken_at == 3


def test_ledger_detects_removed_entries(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for index in range(3):
        ledger.append("note", {"index": index}, moment=1000.0 + index)
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    ledger.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert not ledger.verify().ok
