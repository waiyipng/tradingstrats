"""Per-cycle exit checks: profit-take, stop-loss, and delivery-window unwind for open gold positions."""
from __future__ import annotations

from typing import Any

from ib_async import IB, Contract, Future, LimitOrder

from goldtrading.carry import days_to_expiry, round_to_tick, theoretical_calendar_spread, theoretical_futures_price
from goldtrading.config import GoldConfig
from goldtrading.ibkr_data import LIVE_PORT, PAPER_PORT, quote_for_expiry, spot_quote
from goldtrading.state import close_position, load_state


def _futures_expiry(config: GoldConfig, contract_key: str) -> str:
    return contract_key[len(config.futures_symbol):]


def _current_mispricing_magnitude(config: GoldConfig, ib: IB, position: dict[str, Any]) -> tuple[float | None, bool]:
    """Return (current mispricing magnitude, near-leg approaching last trading day)."""
    spot = spot_quote(ib, config)
    if spot is None or spot.mid_price is None:
        return None, False

    if position["type"] == "cash_and_carry":
        futures_leg = next(leg for leg in position["legs"] if leg["contract"] != config.spot_symbol)
        futures = quote_for_expiry(ib, config, _futures_expiry(config, futures_leg["contract"]))
        if futures is None or futures.mid_price is None:
            return None, False
        fair = theoretical_futures_price(spot.mid_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, futures.days_to_expiry)
        return abs(futures.mid_price - fair), futures.days_to_expiry <= config.last_trading_day_buffer

    near_expiry = _futures_expiry(config, position["legs"][0]["contract"])
    far_expiry = _futures_expiry(config, position["legs"][1]["contract"])
    near = quote_for_expiry(ib, config, near_expiry)
    far = quote_for_expiry(ib, config, far_expiry)
    if near is None or far is None or near.mid_price is None or far.mid_price is None:
        return None, False
    fair_spread = theoretical_calendar_spread(spot.mid_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, near.days_to_expiry, far.days_to_expiry)
    market_spread = far.mid_price - near.mid_price
    return abs(market_spread - fair_spread), near.days_to_expiry <= config.last_trading_day_buffer


def _unwind_legs(ib: IB, config: GoldConfig, legs: list[dict[str, Any]]) -> dict[str, str]:
    results: dict[str, str] = {}
    for leg in legs:
        if leg["contract"] == config.spot_symbol:
            contract: Contract = Contract(secType="CMDTY", symbol=config.spot_symbol, exchange="SMART", currency="USD")
        else:
            contract = Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD", lastTradeDateOrContractMonth=_futures_expiry(config, leg["contract"]))
        details = ib.reqContractDetails(contract)
        if not details:
            results[leg["contract"]] = "could not qualify contract to unwind"
            continue
        qualified = details[0].contract
        closing_action = "SELL" if leg["action"] == "BUY" else "BUY"
        ticker = ib.reqMktData(qualified, snapshot=True)
        ib.sleep(2)
        reference_price = float(ticker.bid or ticker.ask or 0)
        limit_price = round_to_tick(reference_price, float(details[0].minTick or 0.01)) if reference_price > 0 else 0.01
        trade = ib.placeOrder(qualified, LimitOrder(closing_action, leg["quantity"], limit_price))
        ib.sleep(2)
        results[leg["contract"]] = trade.orderStatus.status
    return results


def execute_exit(config: GoldConfig, position_id: str, client_id: int = 47, live: bool = False) -> dict[str, Any]:
    """Unwinds one open position by id. Used both by the paper auto-exit path and,
    once live, by the human-approval gate (goldtrading/approval.py) after a human
    approves a queued exit."""
    state = load_state()
    position = next((p for p in state.get("open_positions", []) if p["id"] == position_id and p["status"] == "open"), None)
    if position is None:
        return {"position_id": position_id, "action": "hold", "reason": "position no longer open"}

    entry_magnitude = float(position.get("entry_mispricing_magnitude", 0.0))
    entry_net_edge = float(position.get("entry_net_edge", 0.0))

    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    try:
        ib.reqMarketDataType(3)  # Delayed data when real-time subscriptions are unavailable.
        current_magnitude, _ = _current_mispricing_magnitude(config, ib, position)
        captured = entry_magnitude - (current_magnitude if current_magnitude is not None else entry_magnitude)
        orders = _unwind_legs(ib, config, position["legs"])
        close_position(position["id"], realized_edge=captured)
        return {"position_id": position["id"], "action": "closed", "orders": orders}
    finally:
        if ib.isConnected():
            ib.disconnect()


def run_monitor_cycle(config: GoldConfig, client_id: int = 47, live: bool = False) -> list[dict[str, Any]]:
    state = load_state()
    open_positions = [position for position in state.get("open_positions", []) if position["status"] == "open"]
    if not open_positions:
        return []

    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    outcomes: list[dict[str, Any]] = []
    try:
        ib.reqMarketDataType(3)  # Delayed data when real-time subscriptions are unavailable.
        for position in open_positions:
            entry_magnitude = float(position.get("entry_mispricing_magnitude", 0.0))
            entry_net_edge = float(position.get("entry_net_edge", 0.0))
            current_magnitude, near_expiry_soon = _current_mispricing_magnitude(config, ib, position)

            if current_magnitude is None:
                outcomes.append({"position_id": position["id"], "action": "hold", "reason": "current quotes unavailable"})
                continue

            captured = entry_magnitude - current_magnitude
            profit_take = entry_net_edge > 0 and captured >= config.profit_take_pct_of_edge * entry_net_edge
            stop_loss = entry_net_edge > 0 and (current_magnitude - entry_magnitude) >= config.stop_loss_edge_multiple * entry_net_edge

            if profit_take or stop_loss or near_expiry_soon:
                reason = "profit target reached" if profit_take else "stop-loss triggered" if stop_loss else "near-month approaching its last trading day"
                if live:
                    from goldtrading.approval import save_pending

                    save_pending("exit", {"position_id": position["id"], "reason": reason})
                    outcomes.append({"position_id": position["id"], "action": "pending_approval", "reason": reason})
                else:
                    orders = _unwind_legs(ib, config, position["legs"])
                    close_position(position["id"], realized_edge=captured)
                    outcomes.append({"position_id": position["id"], "action": "closed", "reason": reason, "orders": orders})
            else:
                outcomes.append({"position_id": position["id"], "action": "hold", "current_mispricing_magnitude": current_magnitude})
        return outcomes
    finally:
        if ib.isConnected():
            ib.disconnect()
