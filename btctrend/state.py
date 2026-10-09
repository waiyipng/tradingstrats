"""Persistent state for the strategy-owned BTC position, its committed target, and fills.

Only quantity bought by this strategy is tracked here; BTC held in the account
for any other reason is never sold by strategy code.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from newstrading.common import load_json

STATE_PATH = Path(__file__).resolve().parent / "data" / "btctrend_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "btc_qty": 0.0,
        "avg_cost": 0.0,
        "held_exposure": 0.0,
        "target_qty": 0.0,
        "target_set_at": None,
        "realized_pnl": 0.0,
        # Trailing-stop state: highest daily close since entry, and whether a stop-out
        # is keeping the strategy flat until a fresh breakout.
        "peak_close": 0.0,
        "stop_locked": False,
        # Entry close of the current trade and whether its one-time profit trim fired.
        "entry_price": 0.0,
        "profit_taken": False,
        "fills": [],
        "updated_at": None,
    }


def load_state() -> dict[str, Any]:
    return {**_default_state(), **load_json(STATE_PATH)} if STATE_PATH.exists() else _default_state()


def save_state(state: dict[str, Any]) -> None:
    """Atomic write: a crash mid-save must never leave a truncated state file."""
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, STATE_PATH)


def apply_fill(
    state: dict[str, Any], action: str, qty: float, price: float, order_id: int | None,
    exec_id: str | None = None, commission: float = 0.0,
) -> float:
    """Update quantity, average cost and realized P&L for a fill; returns the fill's realized P&L.
    Commissions are capitalized into the average cost on buys and deducted on sells."""
    realized = 0.0
    held_qty = float(state["btc_qty"])
    if action == "BUY":
        new_qty = held_qty + qty
        state["avg_cost"] = (held_qty * float(state["avg_cost"]) + qty * price + commission) / new_qty if new_qty > 0 else 0.0
        state["btc_qty"] = new_qty
    else:
        sold = min(qty, held_qty)
        realized = (price - float(state["avg_cost"])) * sold - commission
        state["btc_qty"] = held_qty - sold
        state["realized_pnl"] = float(state["realized_pnl"]) + realized
        if state["btc_qty"] <= 1e-9:
            state["btc_qty"], state["avg_cost"] = 0.0, 0.0
    state["fills"].append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(), "action": action, "qty": qty, "price": price,
            "order_id": order_id, "exec_id": exec_id, "commission": round(commission, 4), "realized_pnl": round(realized, 2),
        }
    )
    return realized


def commit_target(state: dict[str, Any], held_exposure: float, target_qty: float) -> None:
    state["held_exposure"] = held_exposure
    state["target_qty"] = target_qty
    state["target_set_at"] = datetime.now(timezone.utc).isoformat()


def commit_risk_state(state: dict[str, Any], peak_close: float, reentry_locked: bool, entry_price: float, profit_taken: bool) -> None:
    state["peak_close"] = peak_close
    state["stop_locked"] = reentry_locked
    state["entry_price"] = entry_price
    state["profit_taken"] = profit_taken


def known_exec_ids(state: dict[str, Any]) -> set[str]:
    return {fill["exec_id"] for fill in state.get("fills", []) if fill.get("exec_id")}


def ytd_realized_pnl(state: dict[str, Any]) -> float:
    year = str(datetime.now(timezone.utc).year)
    return round(sum(fill.get("realized_pnl", 0.0) for fill in state.get("fills", []) if fill["timestamp"].startswith(year)), 2)
