"""Read-only IBKR paper status used by the dashboard wheel panel."""
from __future__ import annotations

import secrets
from typing import Any

from ib_async import IB, Stock

from wheeltrading.config import WHEEL_CONFIGS
from wheeltrading.ibkr_data import underlying_price
from wheeltrading.state import active_wheel_summary, load_state, move_deep_assignment_to_pool, pool_summary

PAPER_PORT = 7497


def _market_price(ib: IB, symbol: str) -> float | None:
    try:
        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)
        return underlying_price(ib, contract)
    except TimeoutError:
        return None


def wheel_status(client_id: int | None = None) -> dict[str, Any]:
    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id or 20_000 + secrets.randbelow(10_000), timeout=10)
    try:
        positions = ib.positions()
        state = load_state()
        rows = []
        for symbol in WHEEL_CONFIGS:
            price = _market_price(ib, symbol)
            move_deep_assignment_to_pool(symbol, price)
            state = load_state()
            stock_positions = [position for position in positions if position.contract.symbol == symbol and position.contract.secType == "STK"]
            option_positions = [position for position in positions if position.contract.symbol == symbol and position.contract.secType == "OPT" and position.position]
            broker_stock_shares = sum(int(position.position) for position in stock_positions)
            open_options = [
                {
                    "side": "SHORT" if position.position < 0 else "LONG",
                    "right": position.contract.right,
                    "strike": float(position.contract.strike),
                    "expiry": position.contract.lastTradeDateOrContractMonth,
                    "contracts": abs(int(position.position)),
                    "average_cost": float(position.avgCost),
                    "premium": abs(float(position.avgCost)) * 100,
                }
                for position in option_positions
            ]
            pool = pool_summary(state, symbol)
            active_wheel = active_wheel_summary(state, symbol)
            active_wheel_shares = min(broker_stock_shares, int(active_wheel["shares"]))
            pool_shares = int(pool["shares"])
            # Only shares this strategy itself registered via a put assignment (still
            # active, or moved to the pool) count as wheel-owned. Shares bought by the
            # equity-signal strategy or manually outside any automated strategy are
            # real broker holdings but are NOT wheel stock, and must not be reported
            # as such (they also never counted toward covered-call eligibility).
            wheel_shares = active_wheel_shares + pool_shares
            wheel_cost = active_wheel_shares * float(active_wheel["average_cost"]) + pool_shares * float(pool["average_cost"])
            rows.append(
                {
                    "symbol": symbol,
                    "market_price": price,
                    "open_options": open_options,
                    "stock_shares": wheel_shares,
                    "stock_average_cost": round(wheel_cost / wheel_shares, 2) if wheel_shares > 0 else 0.0,
                    "active_wheel_shares": active_wheel_shares,
                    "external_shares": max(0, broker_stock_shares - wheel_shares),
                    "stock_pool": pool,
                    "tracked_options": [item for item in state.get("open_wheel_options", []) if item["symbol"] == symbol],
                }
            )
        return {"connection_mode": "paper", "ytd_realized_pnl": float(state.get("ytd_realized_pnl", 0.0)), "symbols": rows}
    finally:
        if ib.isConnected():
            ib.disconnect()