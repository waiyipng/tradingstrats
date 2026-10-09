"""Paper-only execution of a bull call spread combo order with cash and margin gates."""
from __future__ import annotations

from ib_async import IB, ComboLeg, Contract, LimitOrder

from newstrading.common import usd_exchange_rate, usd_summary_value
from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.ibkr_data import LIVE_PORT, PAPER_PORT, fetch_call_chain
from bullcallspread.models import BullCallSpreadRecommendation, SpreadExecutionReport
from bullcallspread.state import load_state, open_position_count, record_open_position

ACTIVE_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}


def _account_cash(ib: IB) -> float:
    return usd_summary_value(ib.accountSummary(), "TotalCashValue")


def _account_excess_liquidity(ib: IB) -> float:
    return usd_summary_value(ib.accountSummary(), "ExcessLiquidity")


def _margin_impact(ib: IB, contract: Contract, order) -> float:
    try:
        state = ib.whatIfOrder(contract, order)
        # initMarginChange carries no currency of its own and is reported in the
        # account's base currency, so convert to USD the same way account_cash is.
        return abs(float(state.initMarginChange)) / usd_exchange_rate(ib.accountSummary())
    except (TypeError, ValueError, AttributeError):
        return float("inf")


def execute_bull_call_spread(
    config: BullCallSpreadConfig, recommendation: BullCallSpreadRecommendation, client_id: int, live: bool = False
) -> SpreadExecutionReport:
    if (
        recommendation.action != "BUY_BULL_CALL_SPREAD"
        or recommendation.contracts <= 0
        or recommendation.long_leg is None
        or recommendation.short_leg is None
        or recommendation.net_debit is None
    ):
        return SpreadExecutionReport(status="SKIPPED", reason="no actionable bull call spread recommendation")

    if open_position_count(load_state()) >= config.max_concurrent_positions:
        return SpreadExecutionReport(status="REJECTED", reason="max concurrent bull call spread positions already open")

    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    try:
        from datetime import datetime

        target_date = datetime.strptime(recommendation.expiry, "%Y%m%d").date()
        _, _, by_strike = fetch_call_chain(ib, config, target_date)
        long_contract = by_strike.get(recommendation.long_leg.strike)
        short_contract = by_strike.get(recommendation.short_leg.strike)
        if long_contract is None or short_contract is None:
            return SpreadExecutionReport(status="REJECTED", reason="long or short call contract could not be re-qualified")

        ib.reqOpenOrders()
        ib.sleep(0.25)
        if any(
            trade.contract.symbol == config.symbol and trade.contract.secType == "OPT" and trade.orderStatus.status in ACTIVE_STATUSES
            for trade in ib.openTrades()
        ):
            return SpreadExecutionReport(status="REJECTED", reason=f"existing active {config.symbol} option order")

        cash = _account_cash(ib)
        notional = recommendation.net_debit * 100 * recommendation.contracts
        if notional > cash:
            return SpreadExecutionReport(status="REJECTED", reason="insufficient cash for the spread's net debit")

        combo = Contract(
            secType="BAG",
            symbol=config.symbol,
            exchange="SMART",
            currency="USD",
            comboLegs=[
                ComboLeg(conId=long_contract.conId, ratio=1, action="BUY", exchange="SMART"),
                ComboLeg(conId=short_contract.conId, ratio=1, action="SELL", exchange="SMART"),
            ],
        )
        combo_order = LimitOrder("BUY", recommendation.contracts, round(recommendation.net_debit, 2))
        margin_impact = _margin_impact(ib, combo, combo_order)
        excess_liquidity = _account_excess_liquidity(ib)
        if margin_impact > config.max_notional_pct_of_excess_liquidity * excess_liquidity:
            return SpreadExecutionReport(status="REJECTED", reason="spread margin impact exceeds the allocation cap")

        trade = ib.placeOrder(combo, combo_order)
        ib.sleep(2)
        status = trade.orderStatus.status
        if status not in ACTIVE_STATUSES and status != "Filled":
            return SpreadExecutionReport(status=status, reason="combo order was not accepted")

        record_open_position(
            symbol=config.symbol,
            legs=[
                {"strike": recommendation.long_leg.strike, "action": "BUY", "expiry": recommendation.expiry},
                {"strike": recommendation.short_leg.strike, "action": "SELL", "expiry": recommendation.expiry},
            ],
            entry_net_debit=recommendation.net_debit,
            contracts=recommendation.contracts,
        )
        return SpreadExecutionReport(
            status=status,
            reason="live bull call spread combo order submitted" if live else "paper bull call spread combo order submitted",
            order_id=trade.order.orderId,
            limit_price=round(recommendation.net_debit, 2),
        )
    finally:
        if ib.isConnected():
            ib.disconnect()
