"""Read-only IBKR paper status used by the dashboard gold panel."""
from __future__ import annotations

import secrets
from typing import Any

from ib_async import IB

from goldtrading.config import GOLD_CONFIG
from goldtrading.ibkr_data import PAPER_PORT, account_state, futures_quotes, spot_quote
from goldtrading.state import load_state, ytd_realized_pnl


def gold_status(client_id: int | None = None) -> dict[str, Any]:
    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id or 30_000 + secrets.randbelow(10_000), timeout=10)
    try:
        account = account_state(ib)
        spot = spot_quote(ib, GOLD_CONFIG)
        near, far = futures_quotes(ib, GOLD_CONFIG)
        state = load_state()
        open_positions = [position for position in state.get("open_positions", []) if position["status"] == "open"]
        return {
            "connection_mode": "paper",
            "realized_pnl": float(state.get("realized_pnl", 0.0)),
            "ytd_realized_pnl": ytd_realized_pnl(state),
            "account": account.__dict__,
            "spot": spot.__dict__ if spot else None,
            "near_future": near.__dict__ if near else None,
            "far_future": far.__dict__ if far else None,
            "open_positions": open_positions,
        }
    finally:
        if ib.isConnected():
            ib.disconnect()
