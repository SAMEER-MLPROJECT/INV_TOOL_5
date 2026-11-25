from __future__ import annotations

import io
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from sakshya.core.hashing import dump_json, load_json, sha256_bytes
from sakshya.custody.intake import ManifestError, load_manifest
from sakshya.custody.ledger import Ledger
from sakshya.pipeline import ACTIONS_FILE, Analysis, analyse, bundle, ledger_view, load_actions, save_bundle
from sakshya.reach.freeze import linked_cases

CASE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
PACKAGE_DEMO = Path(__file__).resolve().parent.parent / "data" / "demo_cases"
ALLOWED_SUFFIXES = {".csv", ".txt", ".eml", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILES = 400
ACTION_TYPES = {"confirm_link", "reject_link", "forbid_merge", "revoke"}


class WorkspaceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Workspace:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or os.environ.get("SAKSHYA_WORKSPACE", "workspace")).resolve()
        self.cases_dir = self.root / "cases"
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self._analyses: dict[str, Analysis] = {}
        self._bundles: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def seed_demo_cases(self) -> list[str]:
        added = []
        if not PACKAGE_DEMO.exists():
            return added
        for source in sorted(PACKAGE_DEMO.iterdir()):
            target = self.cases_dir / source.name
            if source.is_dir() and not target.exists():
                shutil.copytree(source, target)
                added.append(source.name)
        return added

    def _lock(self, case_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(case_id, threading.Lock())

    def case_dir(self, case_id: str) -> Path:
        if not CASE_ID.match(case_id):
            raise WorkspaceError("Invalid case identifier", 400)
        path = (self.cases_dir / case_id).resolve()
        if self.cases_dir not in path.parents or not (path / "case.yaml").exists():
            raise WorkspaceError("Case not found", 404)
        return path

    def case_ids(self) -> list[str]:
        return sorted(p.name for p in self.cases_dir.iterdir() if (p / "case.yaml").exists() and CASE_ID.match(p.name))

    def analysis(self, case_id: str, refresh: bool = False) -> Analysis:
        with self._lock(case_id):
            if refresh or case_id not in self._analyses:
                self._analyses[case_id] = analyse(self.case_dir(case_id))
                data = bundle(self._analyses[case_id])
                save_bundle(self.case_dir(case_id), data)
                self._bundles[case_id] = data
            return self._analyses[case_id]

    def bundle(self, case_id: str) -> dict[str, Any]:
        self.analysis(case_id)
        data = dict(self._bundles[case_id])
        data["evidence"] = {**data["evidence"], **ledger_view(self.case_dir(case_id))}
        data["linked_cases"] = self.linked(case_id)
        return data

    def summaries(self) -> list[dict[str, Any]]:
        items = []
        for case_id in self.case_ids():
            try:
                data = self.bundle(case_id)
            except (ManifestError, WorkspaceError) as exc:
                items.append({"id": case_id, "title": case_id, "error": str(exc)})
                continue
            items.append(
                {
                    "id": case_id,
                    "title": data["case"]["title"],
                    "decision": data["decision"]["label"],
                    "decision_title": data["decision"]["title"],
                    "score": data["decision"]["score"],
                    "evidence": data["counts"]["evidence"],
                    "observations": data["counts"]["observations"],
                    "complaint_time": data["case"]["complaint_time"],
                }
            )
        return items

    def _interest_entities(self, case_id: str) -> set[str]:
        data = self._bundles.get(case_id)
        if not data:
            return set()
        entities = set()
        for person in data["people"]:
            if person["is_seed"]:
                continue
            for member in person["members"]:
                if member["kind"] in {"phone", "account", "upi", "imei", "email", "cloud"}:
                    entities.add(member["entity"])
        return entities

    def linked(self, case_id: str) -> list[dict[str, Any]]:
        index: dict[str, set[str]] = {}
        for other in self._bundles:
            for entity in self._interest_entities(other):
                index.setdefault(entity, set()).add(other)
        return linked_cases(case_id, self._interest_entities(case_id), index)

    def act(self, case_id: str, kind: str, target: Any, reason: str, actor: str = "investigator") -> dict[str, Any]:
        if kind not in ACTION_TYPES:
            raise WorkspaceError("Unknown action type")
        if not reason or len(reason.strip()) < 3:
            raise WorkspaceError("Give a short reason; it is recorded in the custody ledger")
        case_dir = self.case_dir(case_id)
        with self._lock(case_id):
            actions = load_actions(case_dir)
            if kind == "revoke":
                actions = [a for a in actions if a.get("id") != target]
            else:
                actions = [
                    a
                    for a in actions
                    if not (
                        a.get("target") == target
                        and a["type"] in {"confirm_link", "reject_link"}
                        and kind in {"confirm_link", "reject_link"}
                    )
                ]
                actions.append(
                    {
                        "id": f"A-{uuid.uuid4().hex[:8]}",
                        "type": kind,
                        "target": target,
                        "reason": reason.strip()[:500],
                        "actor": actor[:80],
                        "time": round(time.time(), 3),
                    }
                )
            dump_json(case_dir / ACTIONS_FILE, actions)
            Ledger(case_dir / "ledger.jsonl").append(
                "investigator_action", {"type": kind, "target": target, "reason": reason.strip()[:500], "actor": actor[:80]}
            )
        self.analysis(case_id, refresh=True)
        return self.bundle(case_id)

    def record_report(self, case_id: str, html: str) -> str:
        digest = sha256_bytes(html.encode("utf-8"))
        Ledger(self.case_dir(case_id) / "ledger.jsonl").append("report_export", {"sha256": digest, "format": "html"})
        return digest

    def upload(self, payload: bytes) -> str:
        if len(payload) > MAX_UPLOAD_BYTES:
            raise WorkspaceError("Upload is larger than 25 MB", 413)
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            raise WorkspaceError("Upload must be a .zip archive") from exc
        members = [m for m in archive.infolist() if not m.is_dir()]
        if not members or len(members) > MAX_FILES:
            raise WorkspaceError("Archive is empty or has too many files")
        prefix = _common_prefix([m.filename for m in members])
        staging = self.root / "staging" / uuid.uuid4().hex
        staging.mkdir(parents=True)
        try:
            total = 0
            for member in members:
                name = member.filename[len(prefix) :] if prefix else member.filename
                if not name or name.startswith("/") or ".." in Path(name).parts:
                    raise WorkspaceError("Archive contains an unsafe path")
                suffix = Path(name).suffix.lower()
                if suffix not in ALLOWED_SUFFIXES:
                    raise WorkspaceError(f"File type '{suffix}' is not accepted")
                total += member.file_size
                if total > 4 * MAX_UPLOAD_BYTES:
                    raise WorkspaceError("Archive expands beyond the allowed size", 413)
                target = (staging / name).resolve()
                if staging not in target.parents:
                    raise WorkspaceError("Archive contains an unsafe path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
            manifest = load_manifest(staging)
            case_id = str(manifest["id"])
            if not CASE_ID.match(case_id):
                raise WorkspaceError("case.yaml 'id' may only use letters, digits, '-' and '_'")
            final = self.cases_dir / case_id
            if final.exists():
                raise WorkspaceError(f"A case with id '{case_id}' already exists", 409)
            shutil.move(str(staging), str(final))
        except ManifestError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise WorkspaceError(str(exc)) from exc
        except WorkspaceError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self.analysis(case_id, refresh=True)
        return case_id

    def evaluation(self) -> dict[str, Any] | None:
        path = Path(__file__).resolve().parent.parent / "data" / "evaluation" / "results.json"
        return load_json(path) if path.exists() else None


def _common_prefix(names: list[str]) -> str:
    if any("/" not in n for n in names):
        return ""
    first = {n.split("/", 1)[0] for n in names}
    if len(first) == 1:
        root = next(iter(first)) + "/"
        if any(n == root + "case.yaml" for n in names):
            return root
    return ""
