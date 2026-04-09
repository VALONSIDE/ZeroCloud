from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List
import json


def load_event_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Event store {path} must be a JSON list.")
    rows: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def save_event_rows(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(list(rows), ensure_ascii=False, indent=2)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)


def load_json_object(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return raw


def save_json_object(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)
