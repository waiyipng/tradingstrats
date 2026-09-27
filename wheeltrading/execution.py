"""Paper-only execution for wheel recommendations with duplicate and collateral checks."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ib_async import IB, LimitOrder, Option

from wheeltrading.models import WheelRecommendation
from wheeltrading.state import active_wheel_summary, load_state, track_open_option

PAPER_PORT = 7497
ACTIVE_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}


def _tick_price(price: float, min_tick: float) -> float:
    tick = Decimal(str(min_tick or 0.01))
    return float((Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)


def execute_paper(recommendation: WheelRecommendation, client_id: int = 45) -> dict[str, Any]:
    if recommendation.action == "HOLD" or recommendation.contract is None or recommendation.contracts <= 0:
        return {"status": "SKIPPED", "reason": "no actionable wheel recommendation"}
    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id, timeout=10)
    try:
        ib.reqOpenOrders()
        ib.sleep(0.25)
        if any(trade.contract.symbol == recommendation.symbol and trade.contract.secType == "OPT" and trade.orderStatus.status in ACTIVE_STATUSES for trade in ib.openTrades()):
            return {"status": "REJECTED", "reason": "existing active wheel option order"}
        if any(position.contract.symbol == recommendation.symbol and position.contract.secType == "OPT" and position.position < 0 for position in ib.positions()):
            return {"status": "REJECTED", "reason": "existing short wheel option position"}
        quote = recommendation.contract
        contract = Option(quote.symbol, quote.expiry, quote.strike, quote.right, "SMART", multiplier="100", currency="USD")
        details = ib.reqContractDetails(contract)
        if not details:
            return {"status": "REJECTED", "reason": "option contract could not be qualified"}
        qualified = details[0].contract
        cash = float({row.tag: row.value for row in ib.accountSummary()}.get("TotalCashValue", 0.0))
        if recommendation.action == "SELL_CASH_SECURED_PUT" and recommendation.collateral_required > cash:
            return {"status": "REJECTED", "reason": "cash collateral is insufficient"}
        if recommendation.action == "SELL_COVERED_CALL":
            wheel_shares = int(active_wheel_summary(load_state(), recommendation.symbol)["shares"])
            broker_shares = sum(
                int(position.position)
                for position in ib.positions()
                if position.contract.symbol == recommendation.symbol and position.contract.secType == "STK"
            )
            required_shares = recommendation.contracts * 100
            if min(wheel_shares, broker_shares) < required_shares:
                return {"status": "REJECTED", "reason": "registered wheel shares do not cover this call"}
        limit_price = _tick_price(float(quote.bid or quote.mid_price or 0), float(details[0].minTick))
        if limit_price <= 0:
            return {"status": "REJECTED", "reason": "no valid option bid"}
        trade = ib.placeOrder(qualified, LimitOrder("SELL", recommendation.contracts, limit_price))
        ib.sleep(2)
        status = trade.orderStatus.status
        if status in ACTIVE_STATUSES or status == "Filled":
            track_open_option(recommendation.symbol, quote.right, quote.strike, quote.expiry, recommendation.contracts, limit_price)
        return {"status": status, "order_id": trade.order.orderId, "limit_price": limit_price, "reason": "paper option order submitted"}
    finally:
        if ib.isConnected():
            ib.disconnect()