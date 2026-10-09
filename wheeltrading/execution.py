"""Paper-only execution for wheel recommendations with duplicate and collateral checks."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB, LimitOrder, Option

from newstrading.common import usd_summary_value
from wheeltrading.config import MARKET_CLOSE, MARKET_OPEN, MARKET_TIMEZONE, PORTFOLIO_MAX_ALLOCATION_PCT, get_config
from wheeltrading.ibkr_data import portfolio_put_collateral, symbol_open_contracts
from wheeltrading.models import WheelRecommendation
from wheeltrading.state import active_wheel_summary, load_state, track_open_option

PAPER_PORT = 7497
LIVE_PORT = 7496
ACTIVE_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}


def _tick_price(price: float, min_tick: float) -> float:
    tick = Decimal(str(min_tick or 0.01))
    return float((Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)


def is_market_open(now: datetime | None = None) -> bool:
    """Regular US session, Mon-Fri 9:30-16:00 ET. Exchange holidays are not modelled."""
    local = (now or datetime.now(ZoneInfo(MARKET_TIMEZONE))).astimezone(ZoneInfo(MARKET_TIMEZONE))
    return local.weekday() < 5 and time(*MARKET_OPEN) <= local.time() < time(*MARKET_CLOSE)


def execute_order(recommendation: WheelRecommendation, client_id: int = 45, live: bool = False) -> dict[str, Any]:
    if recommendation.action == "HOLD" or recommendation.contract is None or recommendation.contracts <= 0:
        return {"status": "SKIPPED", "reason": "no actionable wheel recommendation"}
    if not is_market_open():
        return {"status": "SKIPPED", "reason": "outside regular market hours (9:30am-4:00pm ET, Mon-Fri)"}
    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    try:
        ib.reqOpenOrders()
        ib.sleep(0.25)
        if any(trade.contract.symbol == recommendation.symbol and trade.contract.secType == "OPT" and trade.orderStatus.status in ACTIVE_STATUSES for trade in ib.openTrades()):
            return {"status": "REJECTED", "reason": "existing active wheel option order"}
        max_contracts = get_config(recommendation.symbol).max_contracts_per_symbol
        existing_contracts = symbol_open_contracts(ib, recommendation.symbol)
        if existing_contracts + recommendation.contracts > max_contracts:
            return {"status": "REJECTED", "reason": f"would exceed {max_contracts}-contract (200 share) per-symbol wheel limit"}
        quote = recommendation.contract
        contract = Option(quote.symbol, quote.expiry, quote.strike, quote.right, "SMART", multiplier="100", currency="USD")
        details = ib.reqContractDetails(contract)
        if not details:
            return {"status": "REJECTED", "reason": "option contract could not be qualified"}
        qualified = details[0].contract
        account_summary = ib.accountSummary()
        cash = usd_summary_value(account_summary, "TotalCashValue")
        if recommendation.action == "SELL_CASH_SECURED_PUT":
            if recommendation.collateral_required > cash:
                return {"status": "REJECTED", "reason": "cash collateral is insufficient"}
            net_liquidation = usd_summary_value(account_summary, "NetLiquidation", cash)
            existing_collateral = portfolio_put_collateral(ib)
            if existing_collateral + recommendation.collateral_required > net_liquidation * PORTFOLIO_MAX_ALLOCATION_PCT:
                return {"status": "REJECTED", "reason": f"would exceed {PORTFOLIO_MAX_ALLOCATION_PCT:.0%} portfolio collateral cap"}
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
        return {"status": status, "order_id": trade.order.orderId, "limit_price": limit_price, "reason": "live option order submitted" if live else "paper option order submitted"}
    finally:
        if ib.isConnected():
            ib.disconnect()