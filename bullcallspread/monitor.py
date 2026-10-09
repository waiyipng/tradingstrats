"""Tracks unrealized P&L and suggested-exit conditions for an open bull call spread.

This never auto-closes a position; it only records the current mark and flags
whether a suggested exit condition (premium stop or days-before-expiry) has
been reached, matching the tool's "suggest only" exit design.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ib_async import IB, Option

from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.ibkr_data import LIVE_PORT, PAPER_PORT, _snapshot_quote
from bullcallspread.state import load_state, record_pnl_point


def _check_exit_signal(config: BullCallSpreadConfig, expiry: str, current_value: float, entry_net_debit: float) -> str | None:
    stop_value = entry_net_debit * config.stop_loss_pct_of_debit
    if current_value <= stop_value:
        return f"premium stop reached: current value ${current_value:.2f} <= ${stop_value:.2f} ({config.stop_loss_pct_of_debit:.0%} of entry debit)"
    expiry_date = datetime.strptime(expiry, "%Y%m%d").date()
    days_to_expiry = (expiry_date - date.today()).days
    if days_to_expiry <= config.exit_days_before_expiry:
        return f"time-based exit reached: {days_to_expiry} day(s) to expiry (<= {config.exit_days_before_expiry})"
    return None


def run_monitor_cycle(config: BullCallSpreadConfig, client_id: int, live: bool = False) -> dict[str, Any]:
    state = load_state()
    open_positions = [position for position in state.get("open_positions", []) if position["status"] == "open"]
    if not open_positions:
        return {"status": "no_open_positions"}

    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    results = []
    try:
        for position in open_positions:
            legs = position["legs"]
            long_leg = next(leg for leg in legs if leg["action"] == "BUY")
            short_leg = next(leg for leg in legs if leg["action"] == "SELL")
            expiry = long_leg["expiry"]
            contracts = ib.qualifyContracts(
                Option(position["symbol"], expiry, long_leg["strike"], "C", "SMART"),
                Option(position["symbol"], expiry, short_leg["strike"], "C", "SMART"),
            )
            long_quote = _snapshot_quote(ib, contracts[0])
            short_quote = _snapshot_quote(ib, contracts[1])
            if long_quote.bid is None or short_quote.ask is None:
                results.append({"position_id": position["id"], "status": "data_unavailable"})
                continue

            # Conservative mark-to-market: value if closed now (sell the long at its
            # bid, buy back the short at its ask).
            current_value = round(long_quote.bid - short_quote.ask, 2)
            unrealized_pnl = round((current_value - position["entry_net_debit"]) * 100 * position["contracts"], 2)
            exit_signal = _check_exit_signal(config, expiry, current_value, position["entry_net_debit"])
            record_pnl_point(position["id"], current_value, unrealized_pnl, exit_signal)
            results.append(
                {
                    "position_id": position["id"],
                    "current_value": current_value,
                    "unrealized_pnl": unrealized_pnl,
                    "exit_signal": exit_signal,
                }
            )
        return {"status": "ok", "positions": results}
    finally:
        if ib.isConnected():
            ib.disconnect()
