"""Persist inspectable decision records for each scheduled news-trading run."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from newstrading.common import DATA_DIR, load_json, save_json, utcnow_iso

AUDIT_DIR = DATA_DIR / "audit_runs"
RETENTION_DAYS = 14


def audit_path(run_id: str) -> Path:
    return AUDIT_DIR / f"{run_id}.json"


def create_run(run_id: str) -> None:
    path = audit_path(run_id)
    if path.exists():
        return
    save_json(path, {"run_id": run_id, "started_at": utcnow_iso(), "symbols": {}})


def update_symbol(run_id: str | None, symbol: str, **fields: Any) -> None:
    if not run_id:
        return
    create_run(run_id)
    path = audit_path(run_id)
    payload = load_json(path)
    entry = payload.setdefault("symbols", {}).setdefault(symbol, {})
    entry.update(fields)
    entry["updated_at"] = utcnow_iso()
    save_json(path, payload)


def prune_expired_runs(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for path in AUDIT_DIR.glob("*.json"):
        try:
            started_at = load_json(path).get("started_at")
            if not started_at:
                continue
            created = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                path.unlink()
                deleted += 1
        except (OSError, ValueError):
            continue
    return deleted