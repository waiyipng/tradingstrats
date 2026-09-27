"""Allocate one scheduled run's daily buy budget across eligible recommendations."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from newstrading.audit import audit_path, update_symbol
from newstrading.common import DATA_DIR, load_json, new_id, save_json, utcnow_iso
from newstrading.execution.brokers.ibkr_broker import open_buy_notional
from newstrading.execution.risk_manager import (
    MAX_DAILY_BUY_ALLOCATION_PCT,
    completed_daily_buy_notional,
)
from newstrading.models.order_recommendation import OrderRecommendation

SOURCE_QUALITY_MULTIPLIERS = {"primary": 1.35, "professional": 1.15, "secondary": 1.0}


def _quality_multiplier(signal: dict[str, Any]) -> tuple[float, str]:
    tiers = set(signal.get("evidence", {}).get("source_tiers", {}).values())
    if "primary" in tiers:
        return SOURCE_QUALITY_MULTIPLIERS["primary"], "primary"
    if "professional" in tiers:
        return SOURCE_QUALITY_MULTIPLIERS["professional"], "professional"
    return SOURCE_QUALITY_MULTIPLIERS["secondary"], "secondary"


def _proportional_allocations(candidates: list[dict[str, Any]], budget: float) -> dict[str, float]:
    remaining = {candidate["symbol"]: candidate["max_notional"] for candidate in candidates}
    allocated = {candidate["symbol"]: 0.0 for candidate in candidates}
    budget_left = max(0.0, budget)
    while budget_left > 0.01 and remaining:
        active = [candidate for candidate in candidates if remaining[candidate["symbol"]] > 0.01]
        if not active:
            break
        total_weight = sum(candidate["weight"] for candidate in active)
        distributed = 0.0
        for candidate in active:
            symbol = candidate["symbol"]
            share = budget_left * candidate["weight"] / total_weight
            amount = min(share, remaining[symbol])
            allocated[symbol] += amount
            remaining[symbol] -= amount
            distributed += amount
        if distributed <= 0.01:
            break
        budget_left -= distributed
    return allocated


def allocate_run(audit_run_id: str, live: bool = False, client_id: int = 22) -> list[Path]:
    audit = load_json(audit_path(audit_run_id))
    candidates: list[dict[str, Any]] = []
    account = None
    for symbol, entry in audit.get("symbols", {}).items():
        recommendation_data = entry.get("recommendation", {}).get("order")
        signal = entry.get("signaling", {}).get("signal", {})
        if not recommendation_data or recommendation_data.get("action") != "BUY":
            continue
        recommendation = OrderRecommendation.from_dict(recommendation_data)
        if recommendation.qty <= 0 or recommendation.account_snapshot.existing_position_qty > 0:
            continue
        account = account or recommendation.account_snapshot
        multiplier, evidence_quality = _quality_multiplier(signal)
        candidates.append(
            {
                "symbol": symbol,
                "recommendation": recommendation,
                "confidence": float(signal.get("confidence", 0.0)),
                "evidence_quality": evidence_quality,
                "source_multiplier": multiplier,
                "weight": float(signal.get("confidence", 0.0)) * multiplier,
                "max_notional": recommendation.qty * float(recommendation.limit_price or 0),
            }
        )

    if account is None:
        return []
    ranked = sorted(candidates, key=lambda candidate: (-candidate["weight"], candidate["symbol"]))
    selected = ranked
    daily_limit = account.net_liquidation * MAX_DAILY_BUY_ALLOCATION_PCT
    used_notional = completed_daily_buy_notional() + open_buy_notional(live=live, client_id=client_id)
    available_budget = max(0.0, daily_limit - used_notional)
    allocations = _proportional_allocations(selected, available_budget)
    plan: dict[str, Any] = {
        "allocation_plan_id": new_id("alloc"),
        "audit_run_id": audit_run_id,
        "created_at": utcnow_iso(),
        "daily_limit": daily_limit,
        "used_notional_before_plan": used_notional,
        "available_budget": available_budget,
        "candidates": [],
    }
    output_paths: list[Path] = []
    selected_symbols = {candidate["symbol"] for candidate in selected}
    for candidate in ranked:
        recommendation = candidate["recommendation"]
        planned_notional = allocations.get(candidate["symbol"], 0.0)
        qty = recommendation.qty if planned_notional >= candidate["max_notional"] else 0
        reason = "selected" if candidate["symbol"] in selected_symbols else "position-slot ranking"
        if candidate["symbol"] in selected_symbols and qty <= 0:
            reason = "daily budget cannot fund fixed share quantity"
        plan_entry = {
            "symbol": candidate["symbol"],
            "confidence": candidate["confidence"],
            "evidence_quality": candidate["evidence_quality"],
            "source_multiplier": candidate["source_multiplier"],
            "weight": candidate["weight"],
            "requested_notional": candidate["max_notional"],
            "allocated_notional": planned_notional,
            "allocated_qty": qty,
            "reason": reason,
        }
        plan["candidates"].append(plan_entry)
        update_symbol(audit_run_id, candidate["symbol"], allocation=plan_entry)
        if qty <= 0:
            continue
        allocated_recommendation = replace(
            recommendation,
            recommendation_id=new_id("rec_alloc"),
            qty=qty,
            target_allocation_pct=round((qty * float(recommendation.limit_price or 0)) / account.net_liquidation, 4),
        )
        output_path = DATA_DIR / "order_recommendations" / candidate["symbol"] / f"{allocated_recommendation.recommendation_id}.json"
        save_json(output_path, allocated_recommendation.to_dict())
        output_paths.append(output_path)

    save_json(DATA_DIR / "allocation_plans" / f"{plan['allocation_plan_id']}.json", plan)
    return output_paths