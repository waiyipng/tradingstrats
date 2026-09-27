"""Monitor tracked IBKR paper positions for signal-reversal and time-stop exits."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ib_async import IB, MarketOrder

from newstrading.common import DATA_DIR, latest_artifact, load_json, new_id, save_json, utcnow_iso
from newstrading.execution.brokers.ibkr_broker import ACTIVE_ORDER_STATUSES, _execution_status, _stock_contract
from newstrading.models.execution import ExecutionReport, OrderFill, RiskCheckResult
from newstrading.models.order_recommendation import OrderRecommendation
from newstrading.models.signal import TradingSignal
from newstrading.order_recommendation.ibkr_account import connect

STATE_PATH = DATA_DIR / "strategy_positions.json"
MAX_HOLDING_DAYS = 5


def _load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        return load_json(STATE_PATH)
    return {"positions": {}}


def _save_state(state: Dict[str, Any]) -> None:
    save_json(STATE_PATH, state)


def track_entry(order: OrderRecommendation, report: ExecutionReport) -> None:
    if report.status not in {"FILLED", "PARTIAL", "PENDING"}:
        return
    state = _load_state()
    state.setdefault("positions", {})[order.symbol] = {
        "recommendation_id": order.recommendation_id,
        "broker_order_id": report.broker_order_id,
        "opened_at": report.timestamp,
    }
    _save_state(state)


def _exit_reason(entry: Dict[str, Any], signal: Optional[TradingSignal], now: datetime) -> Optional[str]:
    if signal and signal.decision == "SELL":
        return "signal reversal"
    opened_at = datetime.fromisoformat(entry["opened_at"])
    if now - opened_at >= timedelta(days=MAX_HOLDING_DAYS):
        return "time stop"
    return None


def _position_qty(ib: IB, symbol: str) -> int:
    return sum(
        int(position.position)
        for position in ib.positions()
        if position.contract.secType == "STK" and position.contract.symbol == symbol
    )


def _latest_signal(symbol: str) -> Optional[TradingSignal]:
    try:
        return TradingSignal.from_dict(load_json(latest_artifact("signals", symbol)))
    except FileNotFoundError:
        return None


def _cancel_linked_exit_orders(ib: IB, symbol: str, parent_order_id: Optional[int]) -> None:
    for trade in ib.openTrades():
        if (
            trade.contract.symbol == symbol
            and trade.order.action == "SELL"
            and trade.order.parentId == parent_order_id
            and trade.orderStatus.status in ACTIVE_ORDER_STATUSES
        ):
            ib.cancelOrder(trade.order)


def monitor(live: bool = False, client_id: int = 22) -> List[ExecutionReport]:
    state = _load_state()
    tracked_positions = state.setdefault("positions", {})
    reports: List[ExecutionReport] = []
    now = datetime.now(timezone.utc)

    with connect(live=live, client_id=client_id) as ib:
        ib.reqOpenOrders()
        ib.sleep(0.25)
        for symbol, entry in list(tracked_positions.items()):
            quantity = _position_qty(ib, symbol)
            if quantity <= 0:
                del tracked_positions[symbol]
                continue
            if entry.get("exit_order_id"):
                continue

            reason = _exit_reason(entry, _latest_signal(symbol), now)
            if reason is None:
                continue

            _cancel_linked_exit_orders(ib, symbol, entry.get("broker_order_id"))
            contract = _stock_contract(symbol)
            ib.qualifyContracts(contract)
            trade = ib.placeOrder(contract, MarketOrder("SELL", quantity))
            ib.sleep(2)
            filled_qty = int(trade.orderStatus.filled)
            report = ExecutionReport(
                execution_id=new_id("exec"),
                recommendation_id=entry["recommendation_id"],
                symbol=symbol,
                timestamp=utcnow_iso(),
                status=_execution_status(filled_qty, quantity, trade.orderStatus.status),
                broker="ibkr",
                order=OrderFill(
                    requested_qty=quantity,
                    filled_qty=filled_qty,
                    avg_fill_price=float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else None,
                ),
                risk_checks=RiskCheckResult(passed=True, reasons=[reason]),
                broker_order_id=trade.order.orderId,
            )
            reports.append(report)
            entry["exit_order_id"] = trade.order.orderId
            save_json(DATA_DIR / "execution_reports" / symbol / f"{report.execution_id}.json", report.to_dict())

    _save_state(state)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor tracked IBKR positions for exit conditions.")
    parser.add_argument("--live", action="store_true", help="Use live IBKR instead of paper.")
    parser.add_argument("--client-id", type=int, default=22)
    args = parser.parse_args()

    reports = monitor(live=args.live, client_id=args.client_id)
    print(f"Monitored positions; submitted {len(reports)} exit order(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())