"""Human-approval gate for wheeltrading orders, mirroring btctrend/approval.py.

A SELL_CASH_SECURED_PUT / SELL_COVERED_CALL recommendation is held here instead
of being submitted immediately, keyed by symbol since the wheel runs several
symbols per cycle. Only approve_pending (driven by a human action, e.g. the
dashboard's Approve button) actually places an order. A pending record expires
after APPROVAL_WINDOW_MINUTES so a stale, unapproved recommendation is never
filled against an outdated option quote - the next cycle re-evaluates fresh.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ib_async import IB, Option

from newstrading.common import load_json, save_json, utcnow_iso
from wheeltrading.execution import execute_order
from wheeltrading.ibkr_data import LIVE_PORT, PAPER_PORT, _snapshot_quote
from wheeltrading.models import OptionQuote, WheelRecommendation

PENDING_PATH = Path(__file__).resolve().parent / "data" / "pending_approvals.json"
APPROVAL_WINDOW_MINUTES = 30
# If the option's live bid has moved more than this from the pending recommendation's
# bid, refuse to approve blindly - re-run the next cycle against current data instead.
APPROVAL_QUOTE_TOLERANCE_PCT = 0.05


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_all() -> dict[str, Any]:
    if not PENDING_PATH.exists():
        return {}
    try:
        return load_json(PENDING_PATH) or {}
    except (OSError, ValueError):
        return {}


def load_pending(symbol: str | None = None) -> Any:
    pending = _load_all()
    return pending if symbol is None else pending.get(symbol)


def is_expired(entry: dict[str, Any]) -> bool:
    return datetime.now(timezone.utc) > _parse(entry["expires_at"])


def save_pending(symbol: str, recommendation: WheelRecommendation) -> dict[str, Any]:
    pending = _load_all()
    entry = {
        "created_at": utcnow_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_WINDOW_MINUTES)).isoformat(),
        "recommendation": recommendation.to_dict(),
    }
    pending[symbol] = entry
    save_json(PENDING_PATH, pending)
    return entry


def clear_pending(symbol: str) -> None:
    pending = _load_all()
    if symbol in pending:
        del pending[symbol]
        save_json(PENDING_PATH, pending)


def _rebuild_recommendation(rec_dict: dict[str, Any]) -> WheelRecommendation:
    contract = OptionQuote(**rec_dict["contract"]) if rec_dict.get("contract") else None
    return WheelRecommendation(
        symbol=rec_dict["symbol"], action=rec_dict["action"], contracts=rec_dict["contracts"], contract=contract,
        premium_credit=rec_dict["premium_credit"], collateral_required=rec_dict["collateral_required"],
        annualized_yield=rec_dict["annualized_yield"], reasons=rec_dict["reasons"],
    )


def approve_pending(symbol: str, client_id: int, live: bool = False) -> dict[str, Any]:
    pending = load_pending(symbol)
    if pending is None:
        return {"status": "NOT_FOUND", "reason": f"no pending order for {symbol}"}
    if is_expired(pending):
        clear_pending(symbol)
        return {"status": "EXPIRED", "reason": "approval window elapsed; the next scheduler cycle will produce a fresh recommendation"}

    recommendation = _rebuild_recommendation(pending["recommendation"])
    if recommendation.contract is None:
        clear_pending(symbol)
        return {"status": "REJECTED", "reason": "pending recommendation has no option contract"}

    quote = recommendation.contract
    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    try:
        contract = Option(quote.symbol, quote.expiry, quote.strike, quote.right, "SMART", multiplier="100", currency="USD")
        fresh = _snapshot_quote(ib, contract, max_wait_seconds=6.0)
    finally:
        if ib.isConnected():
            ib.disconnect()

    if fresh.bid and quote.bid:
        deviation = abs(fresh.bid / quote.bid - 1)
        if deviation > APPROVAL_QUOTE_TOLERANCE_PCT:
            clear_pending(symbol)
            return {
                "status": "REJECTED",
                "reason": f"option bid moved {deviation:.0%} since the recommendation was queued (tolerance {APPROVAL_QUOTE_TOLERANCE_PCT:.0%}); re-run next cycle",
            }

    try:
        return execute_order(recommendation, client_id, live=live)
    finally:
        clear_pending(symbol)


def reject_pending(symbol: str) -> dict[str, Any]:
    pending = load_pending(symbol)
    if pending is None:
        return {"status": "NOT_FOUND", "reason": f"no pending order for {symbol}"}
    clear_pending(symbol)
    return {"status": "REJECTED", "reason": "rejected by human review"}
