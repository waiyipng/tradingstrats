"""Human-approval gate for live goldtrading orders.

On paper, goldtrading's scheduler and monitor still execute automatically as
before. Once live, an actionable entry (cash-and-carry / calendar-spread) or a
triggered exit (profit-take / stop-loss / last-trading-day unwind) is held here
instead of being submitted immediately. Only approve_pending (driven by a human
action, e.g. the dashboard's Approve button) actually places an order. A pending
record expires after APPROVAL_WINDOW_MINUTES so a stale, unapproved order is never
submitted against an outdated quote - the next scheduler cycle re-evaluates fresh.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from newstrading.common import load_json, save_json, utcnow_iso
from goldtrading.execution import execute_calendar_spread, execute_cash_and_carry
from goldtrading.models import CalendarRecommendation, CarryLadder, CarryRecommendation, FuturesQuote, SpotQuote
from goldtrading.monitor import execute_exit

PENDING_PATH = Path(__file__).resolve().parent / "data" / "pending_approval.json"
APPROVAL_WINDOW_MINUTES = 30

PendingKind = Literal["entry_cash_and_carry", "entry_calendar_spread", "exit"]


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


def save_pending(kind: PendingKind, payload: dict[str, Any]) -> dict[str, Any]:
    pending = {
        "kind": kind,
        "created_at": utcnow_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_WINDOW_MINUTES)).isoformat(),
        "payload": payload,
    }
    save_json(PENDING_PATH, pending)
    return pending


def clear_pending() -> None:
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def _optional_quote(data: dict[str, Any] | None, cls: type) -> Any:
    return cls(**data) if data is not None else None


def _rebuild_carry_recommendation(data: dict[str, Any]) -> CarryRecommendation:
    data = dict(data)
    data["spot"] = _optional_quote(data.get("spot"), SpotQuote)
    data["near_future"] = _optional_quote(data.get("near_future"), FuturesQuote)
    if data.get("ladder") is not None:
        data["ladder"] = CarryLadder(**data["ladder"])
    return CarryRecommendation(**data)


def _rebuild_calendar_recommendation(data: dict[str, Any]) -> CalendarRecommendation:
    data = dict(data)
    data["near_future"] = _optional_quote(data.get("near_future"), FuturesQuote)
    data["far_future"] = _optional_quote(data.get("far_future"), FuturesQuote)
    if data.get("near_ladder") is not None:
        data["near_ladder"] = CarryLadder(**data["near_ladder"])
    if data.get("far_ladder") is not None:
        data["far_ladder"] = CarryLadder(**data["far_ladder"])
    return CalendarRecommendation(**data)


def approve_pending(client_id: int, live: bool = False) -> dict[str, Any]:
    """Re-validates the pending order is still within its approval window and, if
    so, places it. Always clears the pending record - a stale or re-rejected order
    must not keep blocking new cycles."""
    pending = load_pending()
    if pending is None:
        return {"status": "NOT_FOUND", "reason": "no pending order to approve"}
    if is_expired(pending):
        clear_pending()
        return {"status": "EXPIRED", "reason": "approval window elapsed; the next scheduler cycle will re-evaluate fresh"}

    kind = pending["kind"]
    payload = pending["payload"]
    from goldtrading.config import GOLD_CONFIG

    try:
        if kind == "entry_cash_and_carry":
            recommendation = _rebuild_carry_recommendation(payload["recommendation"])
            return execute_cash_and_carry(GOLD_CONFIG, recommendation, client_id, live=live)
        if kind == "entry_calendar_spread":
            recommendation = _rebuild_calendar_recommendation(payload["recommendation"])
            return execute_calendar_spread(GOLD_CONFIG, recommendation, client_id, live=live)
        if kind == "exit":
            return execute_exit(GOLD_CONFIG, payload["position_id"], client_id, live=live)
        return {"status": "REJECTED", "reason": f"unknown pending kind {kind!r}"}
    finally:
        clear_pending()


def reject_pending() -> dict[str, Any]:
    pending = load_pending()
    if pending is None:
        return {"status": "NOT_FOUND", "reason": "no pending order to reject"}
    clear_pending()
    return {"status": "REJECTED", "reason": "rejected by human review"}
