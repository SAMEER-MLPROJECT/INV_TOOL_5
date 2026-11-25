from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sakshya.core.config import colmap, source_types
from sakshya.core.hashing import sha256_file
from sakshya.custody.ledger import Ledger


class ManifestError(ValueError):
    pass


@dataclass
class Evidence:
    evidence_id: str
    file: str
    source: str
    label: str
    sha256: str
    size: int
    entry: dict[str, Any]
    declared_sha256: str | None = None
    integrity: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entry"] = {k: v for k, v in self.entry.items() if k not in {"file", "source"}}
        return data


def load_manifest(case_dir: Path) -> dict[str, Any]:
    path = case_dir / "case.yaml"
    if not path.exists():
        raise ManifestError("case.yaml is missing")
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("id", "evidence"):
        if key not in manifest:
            raise ManifestError(f"case.yaml has no '{key}'")
    known = set(source_types())
    for item in manifest["evidence"]:
        if "file" not in item or "source" not in item:
            raise ManifestError("Each evidence entry needs 'file' and 'source'")
        if item["source"] not in known:
            raise ManifestError(f"Unknown source type '{item['source']}'")
        resolved = (case_dir / item["file"]).resolve()
        if case_dir.resolve() not in resolved.parents:
            raise ManifestError(f"Evidence path '{item['file']}' is outside the case folder")
        if not resolved.exists():
            raise ManifestError(f"Evidence file '{item['file']}' was not found")
    return manifest


def register_evidence(case_dir: Path, manifest: dict[str, Any], ledger: Ledger) -> list[Evidence]:
    known = {entry["payload"]["file"]: entry["payload"]["sha256"] for entry in ledger.entries() if entry["type"] == "intake"}
    items: list[Evidence] = []
    for index, item in enumerate(manifest["evidence"], start=1):
        path = case_dir / item["file"]
        digest = sha256_file(path)
        evidence = Evidence(
            evidence_id=f"E{index:02d}",
            file=item["file"],
            source=item["source"],
            label=colmap(item["source"]).get("label", item["source"]),
            sha256=digest,
            size=path.stat().st_size,
            entry=dict(item),
            declared_sha256=item.get("sha256"),
        )
        if evidence.declared_sha256 and evidence.declared_sha256.lower() != digest:
            evidence.integrity.append(
                {"level": "critical", "message": "File hash differs from the hash declared when it was received"}
            )
        if known.get(item["file"]) is None:
            ledger.append(
                "intake",
                {
                    "evidence_id": evidence.evidence_id,
                    "file": item["file"],
                    "source": item["source"],
                    "sha256": digest,
                    "size": evidence.size,
                },
            )
        elif known[item["file"]] != digest:
            evidence.integrity.append(
                {"level": "critical", "message": "File changed after it was first registered in the ledger"}
            )
            ledger.append(
                "intake_changed",
                {
                    "evidence_id": evidence.evidence_id,
                    "file": item["file"],
                    "previous_sha256": known[item["file"]],
                    "sha256": digest,
                },
            )
        items.append(evidence)
    return items


def check_media(evidence: list[Evidence], frame_hashes: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    findings = []
    by_file = {item.file: item for item in evidence}
    for frame_file, (declared, log_evidence) in frame_hashes.items():
        candidate = by_file.get(f"evidence/{frame_file}") or by_file.get(frame_file)
        if candidate is None:
            findings.append(
                {
                    "file": frame_file,
                    "status": "missing",
                    "log": log_evidence,
                    "message": "Frame listed in the recorder log was not supplied",
                }
            )
            continue
        if declared and candidate.sha256 != declared:
            candidate.integrity.append(
                {"level": "critical", "message": f"Hash does not match the recorder export log ({log_evidence})"}
            )
            findings.append(
                {
                    "file": candidate.file,
                    "status": "mismatch",
                    "log": log_evidence,
                    "evidence_id": candidate.evidence_id,
                    "expected": declared,
                    "actual": candidate.sha256,
                    "message": "Frame was altered after the recorder exported it",
                }
            )
        else:
            findings.append(
                {
                    "file": candidate.file,
                    "status": "verified",
                    "log": log_evidence,
                    "evidence_id": candidate.evidence_id,
                    "message": "Frame matches the recorder export log",
                }
            )
    return findings
