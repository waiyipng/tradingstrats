"""Persistent state for open gold carry/calendar positions and realized P&L."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from newstrading.common import load_json, new_id, save_json

STATE_PATH = Path(__file__).resolve().parent / "data" / "gold_state.json"


def _default_state() -> dict[str, Any]:
    return {"realized_pnl": 0.0, "open_positions": [], "updated_at": None}


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH) if STATE_PATH.exists() else _default_state()


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)


def open_position_count(state: dict[str, Any]) -> int:
    return len([position for position in state.get("open_positions", []) if position["status"] == "open"])


def record_open_position(position_type: str, action: str, legs: list[dict[str, Any]], entry_mispricing_magnitude: float, entry_net_edge: float) -> str:
    state = load_state()
    position_id = new_id(position_type)
    state.setdefault("open_positions", []).append(
        {
            "id": position_id,
            "type": position_type,
            "action": action,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "legs": legs,
            "entry_mispricing_magnitude": entry_mispricing_magnitude,
            "entry_net_edge": entry_net_edge,
            "status": "open",
        }
    )
    save_state(state)
    return position_id


def close_position(position_id: str, realized_edge: float) -> None:
    state = load_state()
    for position in state.get("open_positions", []):
        if position["id"] == position_id and position["status"] == "open":
            position["status"] = "closed"
            position["closed_at"] = datetime.now(timezone.utc).isoformat()
            position["realized_edge"] = realized_edge
            state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + realized_edge
    save_state(state)
