from __future__ import annotations

import copy
import hashlib
import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@cache
def _load_yaml(path: str) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def settings() -> dict[str, Any]:
    return copy.deepcopy(_load_yaml(str(CONFIG_DIR / "settings.yaml")))


def config_file(name: str) -> Any:
    return copy.deepcopy(_load_yaml(str(CONFIG_DIR / name)))


def source_types() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "colmaps").glob("*.yaml"))


def colmap(source: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
    path = CONFIG_DIR / "colmaps" / f"{source}.yaml"
    if not path.exists():
        raise ValueError(f"No column map for source type '{source}'")
    merged = copy.deepcopy(_load_yaml(str(path)))
    for key, value in (override or {}).items():
        if key == "columns" and isinstance(value, dict):
            merged.setdefault("columns", {}).update(value)
        else:
            merged[key] = value
    return merged


def templates() -> list[dict[str, Any]]:
    items = []
    for path in sorted((CONFIG_DIR / "templates").glob("*.yaml")):
        items.append(copy.deepcopy(_load_yaml(str(path))))
    return items


@lru_cache(maxsize=1)
def calibration() -> dict[str, Any]:
    path = CONFIG_DIR / "calibration.json"
    if not path.exists():
        return {"scales": {}, "fitted_on": None}
    return json.loads(path.read_text(encoding="utf-8"))


def calibration_scale(link_type: str) -> float:
    return float(calibration().get("scales", {}).get(link_type, 1.0))


def reload_calibration() -> None:
    calibration.cache_clear()


def config_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(CONFIG_DIR.rglob("*")):
        if path.is_file() and path.suffix in {".yaml", ".json"}:
            digest.update(path.relative_to(CONFIG_DIR).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()
