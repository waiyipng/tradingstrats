"""Persistent state for open bull call spread positions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from newstrading.common import load_json, new_id, save_json

STATE_PATH = Path(__file__).resolve().parent / "data" / "bullcallspread_state.json"


def _default_state() -> dict[str, Any]:
    return {"open_positions": [], "updated_at": None}


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH) if STATE_PATH.exists() else _default_state()


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)


def open_position_count(state: dict[str, Any]) -> int:
    return len([position for position in state.get("open_positions", []) if position["status"] == "open"])


def record_open_position(symbol: str, legs: list[dict[str, Any]], entry_net_debit: float, contracts: int) -> str:
    state = load_state()
    position_id = new_id("bullcallspread")
    state.setdefault("open_positions", []).append(
        {
            "id": position_id,
            "symbol": symbol,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "legs": legs,
            "entry_net_debit": entry_net_debit,
            "contracts": contracts,
            "status": "open",
            "pnl_history": [],
        }
    )
    save_state(state)
    return position_id


def record_pnl_point(position_id: str, current_value: float, unrealized_pnl: float, exit_signal: str | None) -> None:
    state = load_state()
    for position in state.get("open_positions", []):
        if position["id"] == position_id and position["status"] == "open":
            position.setdefault("pnl_history", []).append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "current_value": current_value,
                    "unrealized_pnl": unrealized_pnl,
                    "exit_signal": exit_signal,
                }
            )
    save_state(state)
