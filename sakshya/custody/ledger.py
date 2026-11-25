from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sakshya.core.hashing import canonical_json, sha256_bytes

GENESIS = "0" * 64
_LOCK = threading.Lock()


@dataclass
class LedgerCheck:
    ok: bool
    entries: int
    head: str
    broken_at: int | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "entries": self.entries, "head": self.head, "broken_at": self.broken_at, "message": self.message}


def entry_hash(entry: dict[str, Any]) -> str:
    body = {k: entry[k] for k in ("seq", "time", "type", "payload", "prev")}
    return sha256_bytes(canonical_json(body).encode("utf-8"))


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items

    def head(self) -> str:
        items = self.entries()
        return items[-1]["hash"] if items else GENESIS

    def append(self, kind: str, payload: dict[str, Any], moment: float | None = None) -> dict[str, Any]:
        with _LOCK:
            items = self.entries()
            entry = {
                "seq": len(items) + 1,
                "time": round(moment if moment is not None else time.time(), 3),
                "type": kind,
                "payload": json.loads(canonical_json(payload)),
                "prev": items[-1]["hash"] if items else GENESIS,
            }
            entry["hash"] = entry_hash(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            return entry

    def last(self, kind: str) -> dict[str, Any] | None:
        for entry in reversed(self.entries()):
            if entry["type"] == kind:
                return entry
        return None

    def verify(self) -> LedgerCheck:
        items = self.entries()
        prev = GENESIS
        for index, entry in enumerate(items, start=1):
            if entry.get("seq") != index:
                return LedgerCheck(False, len(items), prev, index, f"Entry {index} is out of sequence")
            if entry.get("prev") != prev:
                return LedgerCheck(False, len(items), prev, index, f"Entry {index} does not point to the previous entry")
            if entry_hash(entry) != entry.get("hash"):
                return LedgerCheck(False, len(items), prev, index, f"Entry {index} was altered after it was written")
            prev = entry["hash"]
        return LedgerCheck(True, len(items), prev, None, "Every entry links to the one before it and no entry was altered")
