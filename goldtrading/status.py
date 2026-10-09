"""Read-only IBKR paper status used by the dashboard gold panel."""
from __future__ import annotations

import os
import secrets
from typing import Any

from ib_async import IB

from goldtrading.config import GOLD_CONFIG
from goldtrading.ibkr_data import LIVE_PORT, PAPER_PORT, account_state, futures_quotes, spot_quote
from goldtrading.state import load_state, ytd_realized_pnl
from trading_config import get_strategy_config

LIVE_CONFIRM_ENV = "GOLDTRADING_LIVE_CONFIRM"


def _is_live() -> bool:
    return get_strategy_config("goldtrading")["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"


def gold_status(client_id: int | None = None) -> dict[str, Any]:
    live = _is_live()
    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id or 30_000 + secrets.randbelow(10_000), timeout=10)
    try:
        account = account_state(ib)
        spot = spot_quote(ib, GOLD_CONFIG)
        near, far = futures_quotes(ib, GOLD_CONFIG)
        state = load_state()
        open_positions = [position for position in state.get("open_positions", []) if position["status"] == "open"]
        return {
            "connection_mode": "live" if live else "paper",
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
