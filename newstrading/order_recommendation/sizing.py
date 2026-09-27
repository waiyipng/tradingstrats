"""Position sizing and risk-parameter rules that turn a trading signal into concrete order terms."""
from __future__ import annotations

from newstrading.common import new_id, utcnow_iso
from newstrading.models.order_recommendation import AccountSnapshot, OrderRecommendation
from newstrading.models.signal import TradingSignal

# Per-sector allocation caps keep any single tech or financial name from dominating the book.
SECTOR_ALLOCATION_CAP_PCT = {"tech": 0.20, "financial": 0.15}
DEFAULT_STOP_LOSS_PCT = 0.03
DEFAULT_TAKE_PROFIT_PCT = 0.06
MAX_SLIPPAGE_PCT = 0.005
FIXED_BUY_QTY = 20


def recommend_order(signal: TradingSignal, account: AccountSnapshot, sector: str) -> OrderRecommendation:
    allocation_cap = SECTOR_ALLOCATION_CAP_PCT.get(sector, 0.10)
    # Scale the allocation cap by signal confidence so weak signals size down automatically.
    target_allocation_pct = round(allocation_cap * signal.confidence, 4)

    limit_price = signal.market_context.current_price
    qty = 0
    if signal.decision == "BUY" and limit_price:
        qty = FIXED_BUY_QTY
    elif signal.decision == "SELL":
        qty = account.existing_position_qty

    action = signal.decision if qty > 0 else "HOLD"

    return OrderRecommendation(
        recommendation_id=new_id("rec"),
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        timestamp=utcnow_iso(),
        action=action,
        order_type="LIMIT",
        qty=qty,
        limit_price=limit_price,
        time_in_force="DAY",
        stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
        take_profit_pct=DEFAULT_TAKE_PROFIT_PCT,
        target_allocation_pct=target_allocation_pct,
        max_slippage_pct=MAX_SLIPPAGE_PCT,
        account_snapshot=account,
    )
