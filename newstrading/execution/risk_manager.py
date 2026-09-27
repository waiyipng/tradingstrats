"""Final pre-trade sanity checks, independent of the sizing logic upstream."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

from newstrading.common import DATA_DIR, load_json
from newstrading.models.order_recommendation import OrderRecommendation

MAX_QTY_PER_ORDER = 5000
MAX_ALLOCATION_PCT = 0.25
MAX_PORTFOLIO_ALLOCATION_PCT = 0.50
MAX_DAILY_BUY_ALLOCATION_PCT = 0.30
US_EASTERN = ZoneInfo("America/New_York")


def completed_daily_buy_notional(now: datetime | None = None) -> float:
    today = (now or datetime.now(US_EASTERN)).astimezone(US_EASTERN).date()
    total = 0.0
    reports_root = DATA_DIR / "execution_reports"
    for path in reports_root.glob("*/*.json"):
        report = load_json(path)
        if report.get("broker") != "ibkr" or report.get("status") not in {"FILLED", "PARTIAL"}:
            continue
        timestamp = datetime.fromisoformat(report["timestamp"].replace("Z", "+00:00"))
        if timestamp.astimezone(US_EASTERN).date() != today:
            continue
        order_data = report.get("order", {})
        total += float(order_data.get("filled_qty", 0)) * float(order_data.get("avg_fill_price") or 0)
    return total


def pre_trade_checks(order: OrderRecommendation, open_buy_notional: float = 0.0) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if order.action == "HOLD" or order.qty <= 0:
        reasons.append("no actionable quantity")
    if order.qty > MAX_QTY_PER_ORDER:
        reasons.append(f"qty {order.qty} exceeds max {MAX_QTY_PER_ORDER}")
    if order.target_allocation_pct > MAX_ALLOCATION_PCT:
        reasons.append(f"allocation {order.target_allocation_pct:.1%} exceeds max {MAX_ALLOCATION_PCT:.0%}")
    if order.limit_price is None or order.limit_price <= 0:
        reasons.append("missing or invalid limit price")
    if order.action == "BUY":
        account = order.account_snapshot
        if account.existing_position_qty > 0:
            reasons.append(f"existing {order.symbol} position prevents duplicate buy")
        current_allocation = account.gross_position_value / account.net_liquidation if account.net_liquidation > 0 else 1.0
        if current_allocation + order.target_allocation_pct > MAX_PORTFOLIO_ALLOCATION_PCT:
            reasons.append(
                f"portfolio allocation {(current_allocation + order.target_allocation_pct):.1%} exceeds max "
                f"{MAX_PORTFOLIO_ALLOCATION_PCT:.0%}"
            )
        proposed_notional = order.qty * order.limit_price
        daily_notional = completed_daily_buy_notional() + open_buy_notional + proposed_notional
        daily_limit = account.net_liquidation * MAX_DAILY_BUY_ALLOCATION_PCT
        if daily_notional > daily_limit:
            reasons.append(
                f"daily buy notional ${daily_notional:,.2f} exceeds {MAX_DAILY_BUY_ALLOCATION_PCT:.0%} "
                f"of net liquidation (${daily_limit:,.2f})"
            )
    return (len(reasons) == 0, reasons)
