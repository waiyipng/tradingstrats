"""Simulated fills against a local JSON paper-account ledger (no live broker connection).

Extracted and generalized from the in-memory paper-trade sim in the legacy
google_news_agent.py so state now persists across runs/symbols.
"""
from __future__ import annotations

from typing import Any, Dict, List

from newstrading.common import DATA_DIR, load_json, new_id, save_json, utcnow_iso
from newstrading.models.execution import ExecutionReport, OrderFill, RiskCheckResult
from newstrading.models.order_recommendation import OrderRecommendation

LEDGER_PATH = DATA_DIR / "paper_account_state.json"
DEFAULT_STARTING_CASH = 100_000.0


def _load_ledger() -> Dict[str, Any]:
    if LEDGER_PATH.exists():
        return load_json(LEDGER_PATH)
    return {"cash": DEFAULT_STARTING_CASH, "positions": {}}


def execute(order: OrderRecommendation, passed: bool, reasons: List[str]) -> ExecutionReport:
    ledger = _load_ledger()
    positions = ledger.setdefault("positions", {})
    current_qty = positions.get(order.symbol, 0)

    if not passed:
        fill = OrderFill(requested_qty=order.qty, filled_qty=0, avg_fill_price=None)
        status = "REJECTED"
    else:
        fill_price = order.limit_price
        if order.action == "BUY":
            ledger["cash"] -= order.qty * fill_price
            positions[order.symbol] = current_qty + order.qty
        elif order.action == "SELL":
            ledger["cash"] += order.qty * fill_price
            positions[order.symbol] = current_qty - order.qty
        fill = OrderFill(requested_qty=order.qty, filled_qty=order.qty, avg_fill_price=fill_price)
        status = "FILLED"

    save_json(LEDGER_PATH, ledger)

    return ExecutionReport(
        execution_id=new_id("exec"),
        recommendation_id=order.recommendation_id,
        symbol=order.symbol,
        timestamp=utcnow_iso(),
        status=status,
        broker="paper",
        order=fill,
        risk_checks=RiskCheckResult(passed=passed, reasons=reasons),
        portfolio_cash_balance=ledger["cash"],
        portfolio_position_qty=positions.get(order.symbol, 0),
    )
