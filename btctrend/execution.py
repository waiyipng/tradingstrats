"""Paper-only execution of a BTC rebalance as a marketable short-GTD limit order."""
from __future__ import annotations

import math

from datetime import datetime, timedelta, timezone
from typing import Any

from ib_async import IB, Crypto, ExecutionFilter, LimitOrder

from btctrend.config import BtcTrendConfig
from btctrend.models import RebalanceRecommendation, TradeExecutionReport
from btctrend.state import apply_fill, commit_risk_state, commit_target, known_exec_ids, load_state, save_state

ACTIVE_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}
FILL_WAIT_SECONDS = 15.0
# A plain IOC requires an instant cross; on live crypto, quote latency between
# computing the limit price and the order reaching the matching engine made that
# miss by a tick and cancel immediately. A short GTD window lets the order rest
# briefly instead, well under the scheduler's cycle interval so it never overlaps
# the next cycle's own order (reqAllOpenOrders already blocks a duplicate while
# one is still resting).
GTD_WINDOW_MINUTES = 2
# IBKR client ids that place strategy orders: the scheduler, the manual CLI, and
# dashboard-approved orders (btctrend/approval.py).
STRATEGY_CLIENT_IDS = {49, 50, 51}
UNSET_COMMISSION = 1e9  # IBKR reports an unset commission as a huge sentinel value


def reconcile_fills(ib: IB, config: BtcTrendConfig) -> list[dict[str, Any]]:
    """Record every strategy BTC execution IBKR reports that the state hasn't seen,
    keyed by execId. Catches fills that land after an order's wait window, which
    would otherwise be missed and re-bought. IBKR only returns the current day's
    executions, so this runs every cycle."""
    state = load_state()
    seen = known_exec_ids(state)
    recorded = []
    for fill in sorted(ib.reqExecutions(ExecutionFilter(secType="CRYPTO")), key=lambda item: item.execution.time):
        execution = fill.execution
        if fill.contract.symbol != config.symbol or execution.clientId not in STRATEGY_CLIENT_IDS or execution.execId in seen:
            continue
        commission = float(fill.commissionReport.commission or 0.0) if fill.commissionReport else 0.0
        if commission >= UNSET_COMMISSION:
            commission = 0.0
        action = "BUY" if execution.side == "BOT" else "SELL"
        apply_fill(state, action, float(execution.shares), float(execution.price), execution.orderId, execution.execId, commission)
        recorded.append({"exec_id": execution.execId, "order_id": execution.orderId, "action": action, "qty": float(execution.shares), "price": float(execution.price), "commission": commission})
    if recorded:
        save_state(state)
    return recorded


def round_to_tick(price: float, tick: float, action: str) -> float:
    """Round onto the contract's price grid, away from the touch so the order stays marketable."""
    steps = price / tick
    return round((math.ceil(steps - 1e-9) if action == "BUY" else math.floor(steps + 1e-9)) * tick, 8)


def execute_rebalance(
    ib: IB, config: BtcTrendConfig, contract: Crypto, recommendation: RebalanceRecommendation, price_tick: float
) -> TradeExecutionReport:
    if recommendation.action == "HOLD" or recommendation.order_qty <= 0 or recommendation.limit_price is None:
        return TradeExecutionReport(status="SKIPPED", reason="no actionable rebalance")

    ib.reqAllOpenOrders()  # every client id, so the scheduler and the CLI can't double up
    ib.sleep(0.5)
    if any(trade.contract.secType == "CRYPTO" and trade.contract.symbol == config.symbol and trade.orderStatus.status in ACTIVE_STATUSES for trade in ib.openTrades()):
        return TradeExecutionReport(status="REJECTED", reason=f"existing active {config.symbol} order")

    limit_price = round_to_tick(recommendation.limit_price, price_tick, recommendation.action)
    order = LimitOrder(recommendation.action, recommendation.order_qty, limit_price, tif="IOC")
    # Rejections such as "no trading permission" (201) arrive as error events, not in trade.log.
    broker_errors: list[str] = []
    on_error = lambda req_id, code, message, _contract: broker_errors.append(f"{code}: {message}") if req_id == order.orderId else None  # noqa: E731
    ib.errorEvent += on_error
    try:
        trade = ib.placeOrder(contract, order)
        waited = 0.0
        while waited < FILL_WAIT_SECONDS and not trade.isDone():
            ib.sleep(0.5)
            waited += 0.5
    finally:
        ib.errorEvent -= on_error

    ib.sleep(1.0)  # let execution and commission reports arrive
    reconcile_fills(ib, config)
    filled = float(trade.orderStatus.filled or 0.0)
    avg_price = float(trade.orderStatus.avgFillPrice or 0.0) or None
    if filled > 0:
        # Commit the new target only once something traded; an unfilled IOC leaves
        # the old target in place so the next cycle re-evaluates from scratch.
        state = load_state()
        commit_target(state, recommendation.new_held_exposure, recommendation.target_qty)
        save_state(state)
    status = trade.orderStatus.status
    broker_message = broker_errors[-1] if broker_errors else next((entry.message for entry in reversed(trade.log) if entry.message), "")
    reason = "paper IOC order filled" if filled >= recommendation.order_qty else (
        f"partially filled {filled:.4f}/{recommendation.order_qty:.4f}; remainder retried next cycle" if filled > 0 else
        f"IOC order not filled ({status}{': ' + broker_message if broker_message else ''}); retried next cycle"
    )
    return TradeExecutionReport(
        status=status, reason=reason, order_id=trade.order.orderId, filled_qty=filled,
        avg_fill_price=avg_price, limit_price=limit_price,
    )


def commit_cycle_state(recommendation: RebalanceRecommendation, order_placed: bool) -> None:
    """Persist the trailing-stop peak and re-entry lock every executed cycle, and a
    band crossing that needed no order, so the next cycle continues from here."""
    state = load_state()
    if not order_placed and recommendation.new_held_exposure != state["held_exposure"]:
        commit_target(state, recommendation.new_held_exposure, recommendation.target_qty)
    commit_risk_state(state, recommendation.peak_close, recommendation.reentry_locked, recommendation.entry_price, recommendation.profit_taken)
    save_state(state)
