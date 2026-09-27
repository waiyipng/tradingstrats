"""Persistent state for wheel assignments, stock pools, and strategy P&L."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from newstrading.common import load_json, save_json

STATE_PATH = Path(__file__).resolve().parent / "data" / "wheel_state.json"
POOL_DRAW_DOWN_PCT = 0.10


def _default_state() -> dict[str, Any]:
    return {"ytd_realized_pnl": 0.0, "assignments": [], "stock_pool": [], "open_wheel_options": [], "updated_at": None}


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH) if STATE_PATH.exists() else _default_state()


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_PATH, state)


def register_put_assignment(symbol: str, shares: int, assigned_strike: float, assigned_at: str) -> None:
    state = load_state()
    state["assignments"].append(
        {
            "symbol": symbol,
            "shares": shares,
            "assigned_strike": assigned_strike,
            "assigned_at": assigned_at,
            "status": "active_wheel_stock",
        }
    )
    save_state(state)


def move_deep_assignment_to_pool(symbol: str, market_price: float | None) -> list[dict[str, Any]]:
    """Move registered assigned lots to the pool once price is 10% below assignment strike."""
    if market_price is None or market_price <= 0:
        return []
    state = load_state()
    moved: list[dict[str, Any]] = []
    for lot in state["assignments"]:
        if lot["symbol"] != symbol or lot["status"] != "active_wheel_stock":
            continue
        if market_price <= lot["assigned_strike"] * (1 - POOL_DRAW_DOWN_PCT):
            lot["status"] = "stock_pool"
            lot["moved_to_pool_at"] = datetime.now(timezone.utc).isoformat()
            lot["pool_trigger_price"] = market_price
            state["stock_pool"].append(dict(lot))
            moved.append(dict(lot))
    if moved:
        save_state(state)
    return moved


def pool_summary(state: dict[str, Any], symbol: str) -> dict[str, float | int]:
    lots = [lot for lot in state.get("stock_pool", []) if lot["symbol"] == symbol]
    shares = sum(int(lot["shares"]) for lot in lots)
    cost = sum(float(lot["shares"]) * float(lot["assigned_strike"]) for lot in lots)
    return {"shares": shares, "average_cost": round(cost / shares, 2) if shares else 0.0}


def active_wheel_summary(state: dict[str, Any], symbol: str) -> dict[str, float | int]:
    lots = [lot for lot in state.get("assignments", []) if lot["symbol"] == symbol and lot["status"] == "active_wheel_stock"]
    shares = sum(int(lot["shares"]) for lot in lots)
    cost = sum(float(lot["shares"]) * float(lot["assigned_strike"]) for lot in lots)
    return {"shares": shares, "average_cost": round(cost / shares, 2) if shares else 0.0}


def track_open_option(symbol: str, right: str, strike: float, expiry: str, contracts: int, premium: float) -> None:
    state = load_state()
    state.setdefault("open_wheel_options", []).append(
        {"symbol": symbol, "right": right, "strike": strike, "expiry": expiry, "contracts": contracts, "premium": premium, "opened_at": datetime.now(timezone.utc).isoformat()}
    )
    save_state(state)