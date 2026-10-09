"""Human-approval gate for btctrend orders.

A BUY/SELL recommendation is held here instead of being submitted immediately.
The scheduler/CLI only ever write a pending record; only approve_pending (driven
by a human action, e.g. the dashboard's Approve button) actually places an order.
A pending record expires after APPROVAL_WINDOW_MINUTES so a stale, unapproved
recommendation is never filled against an outdated price - the next cycle
re-evaluates from scratch instead.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ib_async import IB

from newstrading.common import load_json, save_json, utcnow_iso
from btctrend.config import BtcTrendConfig
from btctrend.execution import execute_rebalance
from btctrend.ibkr_data import btc_contract, btc_quote_with_fallback, connect
from btctrend.models import RebalanceRecommendation

PENDING_PATH = Path(__file__).resolve().parent / "data" / "pending_approval.json"
APPROVAL_WINDOW_MINUTES = 30
# If the live quote has moved more than this from the pending limit price, refuse to
# approve blindly - the recommendation is stale and should be rejected so the next
# scheduler cycle re-evaluates against current data instead of chasing an old price.
APPROVAL_PRICE_TOLERANCE_PCT = 0.02


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_pending() -> dict[str, Any] | None:
    if not PENDING_PATH.exists():
        return None
    try:
        return load_json(PENDING_PATH) or None
    except (OSError, ValueError):
        return None


def is_expired(pending: dict[str, Any]) -> bool:
    return datetime.now(timezone.utc) > _parse(pending["expires_at"])


def save_pending(recommendation: RebalanceRecommendation) -> dict[str, Any]:
    pending = {
        "created_at": utcnow_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_WINDOW_MINUTES)).isoformat(),
        "recommendation": recommendation.to_dict(),
    }
    save_json(PENDING_PATH, pending)
    return pending


def clear_pending() -> None:
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def approve_pending(config: BtcTrendConfig, client_id: int, live: bool = False) -> dict[str, Any]:
    """Re-validates the pending recommendation against a fresh quote and, if it
    still holds up, places the order. Always clears the pending record - a stale
    or re-rejected recommendation must not keep blocking new cycles."""
    pending = load_pending()
    if pending is None:
        return {"status": "NOT_FOUND", "reason": "no pending order to approve"}
    if is_expired(pending):
        clear_pending()
        return {"status": "EXPIRED", "reason": "approval window elapsed; the next scheduler cycle will produce a fresh recommendation"}

    recommendation = RebalanceRecommendation(**pending["recommendation"])
    if recommendation.limit_price is None:
        clear_pending()
        return {"status": "REJECTED", "reason": "pending recommendation has no limit price"}

    ib = connect(client_id, live=live)
    try:
        contract, _increment, price_tick = btc_contract(ib, config)
        quote = btc_quote_with_fallback(ib, contract)
        current = quote.ask if recommendation.action == "BUY" else quote.bid
        if not current:
            return {"status": "REJECTED", "reason": "no live BTC quote available to validate the order"}
        deviation = abs(current / recommendation.limit_price - 1)
        if deviation > APPROVAL_PRICE_TOLERANCE_PCT:
            clear_pending()
            return {
                "status": "REJECTED",
                "reason": f"quote moved {deviation:.1%} since the recommendation was queued (tolerance {APPROVAL_PRICE_TOLERANCE_PCT:.0%}); re-run next cycle",
            }
        report = execute_rebalance(ib, config, contract, recommendation, price_tick)
        return asdict(report)
    finally:
        clear_pending()
        if ib.isConnected():
            ib.disconnect()


def reject_pending() -> dict[str, Any]:
    pending = load_pending()
    if pending is None:
        return {"status": "NOT_FOUND", "reason": "no pending order to reject"}
    clear_pending()
    return {"status": "REJECTED", "reason": "rejected by human review"}
