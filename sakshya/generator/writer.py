from __future__ import annotations

import csv
import io
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sakshya.core.hashing import dump_json, sha256_bytes


@dataclass
class TableFile:
    name: str
    source: str
    columns: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    sort_key: str | None = None

    def add(self, row: dict[str, Any], tag: str | None = None) -> RowRef:
        self.rows.append({"__tag": tag, **row})
        return RowRef(self.name, len(self.rows) - 1)


@dataclass
class TextFile:
    name: str
    source: str
    lines: list[tuple[str, str | None]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def add(self, line: str, tag: str | None = None) -> RowRef:
        self.lines.append((line, tag))
        return RowRef(self.name, len(self.lines) - 1)


@dataclass
class BlobFile:
    name: str
    source: str
    content: bytes
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RowRef:
    file: str
    index: int


class CaseWriter:
    def __init__(self, case_id: str, title: str) -> None:
        self.case_id = case_id
        self.title = title
        self.tables: dict[str, TableFile] = {}
        self.texts: dict[str, TextFile] = {}
        self.blobs: dict[str, BlobFile] = {}
        self.order: list[str] = []
        self.manifest_extra: dict[str, Any] = {}
        self.seed_identifiers: list[dict[str, str]] = []
        self.seed_kind = "complaint"
        self.truth: dict[str, Any] = {}
        self.ref_tags: dict[str, list[RowRef]] = {}

    def table(self, name: str, source: str, columns: list[str], sort_key: str | None = None, **options: Any) -> TableFile:
        if name not in self.tables:
            self.tables[name] = TableFile(name, source, columns, options=options, sort_key=sort_key)
            self.order.append(name)
        return self.tables[name]

    def text(self, name: str, source: str, **options: Any) -> TextFile:
        if name not in self.texts:
            self.texts[name] = TextFile(name, source, options=options)
            self.order.append(name)
        return self.texts[name]

    def blob(self, name: str, source: str, content: bytes, **options: Any) -> None:
        self.blobs[name] = BlobFile(name, source, content, options=options)
        self.order.append(name)

    def tag(self, key: str, ref: RowRef) -> None:
        self.ref_tags.setdefault(key, []).append(ref)

    def _final_rows(self, table: TableFile) -> tuple[list[dict[str, Any]], dict[int, int]]:
        indexed = list(enumerate(table.rows))
        if table.sort_key:
            indexed.sort(key=lambda item: (str(item[1].get(table.sort_key, "")), item[0]))
        mapping = {orig: pos for pos, (orig, _) in enumerate(indexed)}
        return [row for _, row in indexed], mapping

    def write(self, out_dir: Path) -> Path:
        evidence_dir = out_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        line_maps: dict[str, dict[int, int]] = {}
        evidence_entries = []
        for name in self.order:
            path = evidence_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name in self.tables:
                table = self.tables[name]
                rows, mapping = self._final_rows(table)
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=table.columns, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in table.columns})
                path.write_text(buffer.getvalue(), encoding="utf-8")
                line_maps[name] = {orig: pos + 2 for orig, pos in mapping.items()}
                entry = {"file": f"evidence/{name}", "source": table.source}
                entry.update(table.options)
            elif name in self.texts:
                text = self.texts[name]
                if text.options.get("raw_json"):
                    path.write_text(text.lines[0][0], encoding="utf-8")
                    line_maps[name] = {i: i + 1 for i in range(len(text.lines))}
                else:
                    path.write_text("\n".join(line for line, _ in text.lines) + "\n", encoding="utf-8")
                    line_maps[name] = {i: i + 1 for i in range(len(text.lines))}
                entry = {"file": f"evidence/{name}", "source": text.source}
                entry.update({k: v for k, v in text.options.items() if k != "raw_json"})
            else:
                blob = self.blobs[name]
                path.write_bytes(blob.content)
                line_maps[name] = {0: 1}
                entry = {"file": f"evidence/{name}", "source": blob.source}
                entry.update(blob.options)
            evidence_entries.append(entry)
        manifest = {
            "id": self.case_id,
            "title": self.title,
            "seed": {"kind": self.seed_kind, "identifiers": self.seed_identifiers},
            "evidence": evidence_entries,
        }
        manifest.update(self.manifest_extra)
        (out_dir / "case.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
        truth = self._resolve_truth(self.truth, line_maps)
        dump_json(out_dir / "truth.json", truth)
        return out_dir

    def _resolve_truth(self, value: Any, line_maps: dict[str, dict[int, int]]) -> Any:
        if isinstance(value, RowRef):
            return [f"evidence/{value.file}", line_maps[value.file][value.index]]
        if isinstance(value, dict):
            return {k: self._resolve_truth(v, line_maps) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._resolve_truth(v, line_maps) for v in value]
        return value


def png_bytes(width: int, height: int, seed: int, shade: int = 90) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            value = (shade + ((x * 7 + y * 13 + seed * 31) % 40)) & 0xFF
            rows.extend((value, value, min(255, value + 8)))
    raw = zlib.compress(bytes(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def frame_hash(content: bytes) -> str:
    return sha256_bytes(content)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
