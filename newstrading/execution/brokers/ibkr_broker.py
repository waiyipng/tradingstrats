"""Live/paper IBKR order placement via ib_async, mirroring optiontrading's connect/placeOrder pattern."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List

from ib_async import IB, LimitOrder, Stock, StopOrder

from newstrading.common import new_id, utcnow_iso
from newstrading.config.loader import get_symbol_entry
from newstrading.models.execution import ExecutionReport, OrderFill, RiskCheckResult
from newstrading.models.order_recommendation import OrderRecommendation

PAPER_PORT = 7497
LIVE_PORT = 7496

ACTIVE_ORDER_STATUSES = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}


def _stock_contract(symbol: str) -> Stock:
    entry = get_symbol_entry(symbol)
    return Stock(
        entry["symbol"],
        entry.get("exchange", "SMART"),
        entry.get("currency", "USD"),
    )


def _price_for_tick(price: float, min_tick: float) -> float:
    tick = Decimal(str(min_tick))
    if tick <= 0:
        tick = Decimal("0.01")
    return float((Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)


def _bracket_orders(order: OrderRecommendation, parent_order_id: int, min_tick: float) -> List[LimitOrder | StopOrder]:
    entry_price = _price_for_tick(order.limit_price, min_tick)
    entry = LimitOrder(
        order.action,
        order.qty,
        entry_price,
        orderId=parent_order_id,
        tif=order.time_in_force,
        transmit=False,
    )
    if order.action != "BUY" or order.stop_loss_pct <= 0 or order.take_profit_pct <= 0:
        entry.transmit = True
        return [entry]

    exit_action = "SELL"
    take_profit = LimitOrder(
        exit_action,
        order.qty,
        _price_for_tick(entry_price * (1 + order.take_profit_pct), min_tick),
        parentId=parent_order_id,
        tif="GTC",
        transmit=False,
    )
    stop_loss = StopOrder(
        exit_action,
        order.qty,
        _price_for_tick(entry_price * (1 - order.stop_loss_pct), min_tick),
        parentId=parent_order_id,
        tif="GTC",
        transmit=True,
    )
    return [entry, take_profit, stop_loss]


def _execution_status(filled_qty: int, requested_qty: int, broker_status: str) -> str:
    if filled_qty >= requested_qty:
        return "FILLED"
    if filled_qty > 0:
        return "PARTIAL"
    if broker_status in ACTIVE_ORDER_STATUSES:
        return "PENDING"
    if broker_status in {"Cancelled", "ApiCancelled", "Inactive"}:
        return "CANCELLED"
    return "REJECTED"


def _has_open_buy_order(ib: IB, symbol: str) -> bool:
    ib.reqOpenOrders()
    ib.sleep(0.25)
    return any(
        trade.contract.symbol == symbol
        and trade.order.action == "BUY"
        and trade.orderStatus.status in ACTIVE_ORDER_STATUSES
        for trade in ib.openTrades()
    )


def open_buy_notional(host: str = "127.0.0.1", live: bool = False, client_id: int = 22) -> float:
    ib = IB()
    port = LIVE_PORT if live else PAPER_PORT
    ib.connect(host, port, clientId=client_id)
    try:
        ib.reqOpenOrders()
        ib.sleep(0.25)
        return sum(
            float(trade.order.totalQuantity) * float(trade.order.lmtPrice or 0)
            for trade in ib.openTrades()
            if trade.contract.secType == "STK"
            and trade.order.action == "BUY"
            and trade.orderStatus.status in ACTIVE_ORDER_STATUSES
        )
    finally:
        if ib.isConnected():
            ib.disconnect()


def execute(
    order: OrderRecommendation,
    passed: bool,
    reasons: List[str],
    host: str = "127.0.0.1",
    live: bool = False,
    client_id: int = 22,
    dry_run: bool = True,
) -> ExecutionReport:
    if not passed:
        fill = OrderFill(requested_qty=order.qty, filled_qty=0, avg_fill_price=None)
        return ExecutionReport(
            execution_id=new_id("exec"),
            recommendation_id=order.recommendation_id,
            symbol=order.symbol,
            timestamp=utcnow_iso(),
            status="REJECTED",
            broker="ibkr",
            order=fill,
            risk_checks=RiskCheckResult(passed=passed, reasons=reasons),
        )

    if dry_run:
        fill = OrderFill(requested_qty=order.qty, filled_qty=0, avg_fill_price=order.limit_price)
        return ExecutionReport(
            execution_id=new_id("exec"),
            recommendation_id=order.recommendation_id,
            symbol=order.symbol,
            timestamp=utcnow_iso(),
            status="DRY_RUN",
            broker="ibkr",
            order=fill,
            risk_checks=RiskCheckResult(passed=passed, reasons=reasons),
        )

    ib = IB()
    port = LIVE_PORT if live else PAPER_PORT
    ib.connect(host, port, clientId=client_id)
    try:
        contract = _stock_contract(order.symbol)
        ib.qualifyContracts(contract)
        contract_details = ib.reqContractDetails(contract)
        min_tick = float(contract_details[0].minTick) if contract_details else 0.01
        if order.action == "BUY" and _has_open_buy_order(ib, order.symbol):
            fill = OrderFill(requested_qty=order.qty, filled_qty=0, avg_fill_price=None)
            return ExecutionReport(
                execution_id=new_id("exec"),
                recommendation_id=order.recommendation_id,
                symbol=order.symbol,
                timestamp=utcnow_iso(),
                status="REJECTED",
                broker="ibkr",
                order=fill,
                risk_checks=RiskCheckResult(passed=False, reasons=[*reasons, "open buy order already exists"]),
            )
        parent_order_id = ib.client.getReqId()
        trades = [ib.placeOrder(contract, child_order) for child_order in _bracket_orders(order, parent_order_id, min_tick)]
        trade = trades[0]
        ib.sleep(2)
        filled_qty = int(trade.orderStatus.filled)
        avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else None
        status = _execution_status(filled_qty, order.qty, trade.orderStatus.status)
        fill = OrderFill(requested_qty=order.qty, filled_qty=filled_qty, avg_fill_price=avg_price)
        summary = {row.tag: row.value for row in ib.accountSummary()}
        cash_balance = float(summary.get("TotalCashValue", 0.0))
    finally:
        if ib.isConnected():
            ib.disconnect()

    return ExecutionReport(
        execution_id=new_id("exec"),
        recommendation_id=order.recommendation_id,
        symbol=order.symbol,
        timestamp=utcnow_iso(),
        status=status,
        broker="ibkr",
        order=fill,
        risk_checks=RiskCheckResult(passed=passed, reasons=reasons),
        broker_order_id=trade.order.orderId,
        portfolio_cash_balance=cash_balance,
    )
