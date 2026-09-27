"""Shared utilities: JSON I/O, id/timestamp generation, and data artifact paths."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

NEWSTRADING_ROOT = Path(__file__).resolve().parent
DATA_DIR = NEWSTRADING_ROOT / "data"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def load_json(path: "Path | str") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def latest_artifact(stage: str, symbol: str) -> Path:
    """Return the most recently modified JSON artifact for a symbol within a stage directory."""
    directory = DATA_DIR / stage / symbol.upper()
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No artifacts found in {directory}")
    return files[-1]
