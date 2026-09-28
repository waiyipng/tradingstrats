"""Paper-only execution for gold carry/calendar recommendations with margin and cash gates."""
from __future__ import annotations

from typing import Any

from ib_async import IB, ComboLeg, Contract, Future, LimitOrder

from goldtrading.carry import round_to_tick
from goldtrading.config import GoldConfig
from goldtrading.models import CalendarRecommendation, CarryRecommendation
from goldtrading.state import load_state, open_position_count, record_open_position

PAPER_PORT = 7497
ACTIVE_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}


def _account_cash(ib: IB) -> float:
    return float({row.tag: row.value for row in ib.accountSummary()}.get("TotalCashValue", 0.0))


def _margin_impact(ib: IB, contract: Contract, order) -> float:
    try:
        state = ib.whatIfOrder(contract, order)
        return abs(float(state.initMarginChange))
    except (TypeError, ValueError, AttributeError):
        return float("inf")


def execute_cash_and_carry(config: GoldConfig, recommendation: CarryRecommendation, client_id: int = 46) -> dict[str, Any]:
    if recommendation.action != "CASH_AND_CARRY" or recommendation.contracts <= 0 or recommendation.spot is None or recommendation.near_future is None:
        return {"status": "SKIPPED", "reason": "no actionable cash-and-carry recommendation"}

    if open_position_count(load_state()) >= config.max_concurrent_positions:
        return {"status": "REJECTED", "reason": "max concurrent gold positions already open"}

    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id, timeout=10)
    try:
        spot_contract = Contract(secType="CMDTY", symbol=config.spot_symbol, exchange="SMART", currency="USD")
        spot_details = ib.reqContractDetails(spot_contract)
        futures_contract = Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD", lastTradeDateOrContractMonth=recommendation.near_future.expiry)
        futures_details = ib.reqContractDetails(futures_contract)
        if not spot_details or not futures_details:
            return {"status": "REJECTED", "reason": "spot or futures contract could not be qualified"}
        qualified_spot = spot_details[0].contract
        qualified_futures = futures_details[0].contract

        ib.reqOpenOrders()
        ib.sleep(0.25)
        if any(trade.contract.symbol in (config.spot_symbol, config.futures_symbol) and trade.orderStatus.status in ACTIVE_STATUSES for trade in ib.openTrades()):
            return {"status": "REJECTED", "reason": "existing active gold order"}

        cash = _account_cash(ib)
        spot_price = recommendation.spot.ask or recommendation.spot.mid_price or 0.0
        futures_price = recommendation.near_future.bid or recommendation.near_future.mid_price or 0.0
        if spot_price <= 0 or futures_price <= 0:
            return {"status": "REJECTED", "reason": "no valid bid/ask for the spot or futures leg"}

        spot_notional = spot_price * recommendation.spot_quantity_oz
        if spot_notional > cash:
            return {"status": "REJECTED", "reason": "insufficient cash for the spot leg"}

        futures_order = LimitOrder("SELL", recommendation.contracts, round_to_tick(futures_price, float(futures_details[0].minTick or 0.10)))
        margin_impact = _margin_impact(ib, qualified_futures, futures_order)
        if margin_impact > config.max_notional_pct_of_net_liq * cash:
            return {"status": "REJECTED", "reason": "futures leg margin impact exceeds the allocation cap"}

        spot_order = LimitOrder("BUY", recommendation.spot_quantity_oz, round_to_tick(spot_price, float(spot_details[0].minTick or 0.01)))
        spot_trade = ib.placeOrder(qualified_spot, spot_order)
        ib.sleep(2)
        if spot_trade.orderStatus.status not in ACTIVE_STATUSES and spot_trade.orderStatus.status != "Filled":
            return {"status": spot_trade.orderStatus.status, "reason": "spot leg order was not accepted"}

        futures_trade = ib.placeOrder(qualified_futures, futures_order)
        ib.sleep(2)
        if futures_trade.orderStatus.status not in ACTIVE_STATUSES and futures_trade.orderStatus.status != "Filled":
            ib.cancelOrder(spot_order)
            unwind_order = LimitOrder("SELL", recommendation.spot_quantity_oz, round_to_tick(spot_price, float(spot_details[0].minTick or 0.01)))
            ib.placeOrder(qualified_spot, unwind_order)
            return {"status": "leg_unwind_required", "reason": "futures leg was rejected after the spot leg was submitted; an unwind order was sent"}

        record_open_position(
            position_type="cash_and_carry",
            action=recommendation.action,
            legs=[
                {"contract": config.spot_symbol, "action": "BUY", "quantity": recommendation.spot_quantity_oz},
                {"contract": f"{config.futures_symbol}{recommendation.near_future.expiry}", "action": "SELL", "quantity": recommendation.contracts},
            ],
            entry_mispricing_magnitude=abs(recommendation.entry_basis or 0.0),
            entry_net_edge=recommendation.net_edge_after_costs or 0.0,
        )
        return {
            "status": "SUBMITTED",
            "spot_order_id": spot_trade.order.orderId,
            "futures_order_id": futures_trade.order.orderId,
            "reason": "paper cash-and-carry orders submitted",
        }
    finally:
        if ib.isConnected():
            ib.disconnect()


def execute_calendar_spread(config: GoldConfig, recommendation: CalendarRecommendation, client_id: int = 46) -> dict[str, Any]:
    if recommendation.action not in ("SELL_CALENDAR_SPREAD", "BUY_CALENDAR_SPREAD") or recommendation.contracts <= 0 or recommendation.near_future is None or recommendation.far_future is None:
        return {"status": "SKIPPED", "reason": "no actionable calendar-spread recommendation"}

    if open_position_count(load_state()) >= config.max_concurrent_positions:
        return {"status": "REJECTED", "reason": "max concurrent gold positions already open"}

    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id, timeout=10)
    try:
        near_details = ib.reqContractDetails(Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD", lastTradeDateOrContractMonth=recommendation.near_future.expiry))
        far_details = ib.reqContractDetails(Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD", lastTradeDateOrContractMonth=recommendation.far_future.expiry))
        if not near_details or not far_details:
            return {"status": "REJECTED", "reason": "near or far futures contract could not be qualified"}
        near_contract = near_details[0].contract
        far_contract = far_details[0].contract

        ib.reqOpenOrders()
        ib.sleep(0.25)
        if any(trade.contract.symbol == config.futures_symbol and trade.orderStatus.status in ACTIVE_STATUSES for trade in ib.openTrades()):
            return {"status": "REJECTED", "reason": "existing active gold futures order"}

        near_price = recommendation.near_future.mid_price or 0.0
        far_price = recommendation.far_future.mid_price or 0.0
        if near_price <= 0 or far_price <= 0:
            return {"status": "REJECTED", "reason": "no valid bid/ask for the near or far futures leg"}

        # SELL_CALENDAR_SPREAD: buy the (cheap) near leg, sell the (rich) far leg.
        # BUY_CALENDAR_SPREAD: sell the (rich) near leg, buy the (cheap) far leg.
        near_action, far_action = ("BUY", "SELL") if recommendation.action == "SELL_CALENDAR_SPREAD" else ("SELL", "BUY")
        min_tick = recommendation.near_future.min_tick or 0.10
        raw_price = (near_price - far_price) if recommendation.action == "SELL_CALENDAR_SPREAD" else (far_price - near_price)
        limit_price = round_to_tick(raw_price, min_tick)

        combo = Contract(
            secType="BAG",
            symbol=config.futures_symbol,
            exchange=config.futures_exchange,
            currency="USD",
            comboLegs=[
                ComboLeg(conId=near_contract.conId, ratio=1, action=near_action, exchange=config.futures_exchange),
                ComboLeg(conId=far_contract.conId, ratio=1, action=far_action, exchange=config.futures_exchange),
            ],
        )
        combo_order = LimitOrder("BUY", recommendation.contracts, limit_price)
        cash = _account_cash(ib)
        margin_impact = _margin_impact(ib, combo, combo_order)
        if margin_impact > config.max_notional_pct_of_net_liq * cash:
            return {"status": "REJECTED", "reason": "calendar spread margin impact exceeds the allocation cap"}

        trade = ib.placeOrder(combo, combo_order)
        ib.sleep(2)
        status = trade.orderStatus.status
        legs = [
            {"contract": f"{config.futures_symbol}{recommendation.near_future.expiry}", "action": near_action, "quantity": recommendation.contracts},
            {"contract": f"{config.futures_symbol}{recommendation.far_future.expiry}", "action": far_action, "quantity": recommendation.contracts},
        ]
        if status in ACTIVE_STATUSES or status == "Filled":
            record_open_position(
                position_type="calendar_spread",
                action=recommendation.action,
                legs=legs,
                entry_mispricing_magnitude=abs(recommendation.mispricing or 0.0),
                entry_net_edge=recommendation.net_edge_after_costs or 0.0,
            )
            return {"status": status, "order_id": trade.order.orderId, "limit_price": limit_price, "reason": "paper calendar spread combo order submitted"}

        # The combo was rejected outright (e.g. spreads unsupported for this contract) — fall back
        # to two sequential single-leg orders, near leg first.
        near_order = LimitOrder(near_action, recommendation.contracts, round_to_tick(near_price, min_tick))
        near_trade = ib.placeOrder(near_contract, near_order)
        ib.sleep(2)
        if near_trade.orderStatus.status not in ACTIVE_STATUSES and near_trade.orderStatus.status != "Filled":
            return {"status": "REJECTED", "reason": "combo order and the near-leg fallback order were both rejected"}

        far_order = LimitOrder(far_action, recommendation.contracts, round_to_tick(far_price, recommendation.far_future.min_tick or 0.10))
        far_trade = ib.placeOrder(far_contract, far_order)
        ib.sleep(2)
        if far_trade.orderStatus.status not in ACTIVE_STATUSES and far_trade.orderStatus.status != "Filled":
            unwind_action = "SELL" if near_action == "BUY" else "BUY"
            ib.placeOrder(near_contract, LimitOrder(unwind_action, recommendation.contracts, round_to_tick(near_price, min_tick)))
            return {"status": "leg_unwind_required", "reason": "far leg was rejected after the near leg filled; an unwind order was sent"}

        record_open_position(
            position_type="calendar_spread",
            action=recommendation.action,
            legs=legs,
            entry_mispricing_magnitude=abs(recommendation.mispricing or 0.0),
            entry_net_edge=recommendation.net_edge_after_costs or 0.0,
        )
        return {
            "status": "SUBMITTED",
            "near_order_id": near_trade.order.orderId,
            "far_order_id": far_trade.order.orderId,
            "reason": "paper calendar spread legs submitted sequentially after the combo order was rejected",
        }
    finally:
        if ib.isConnected():
            ib.disconnect()
