"""Pure adapters converting already-fetched IBKR Connector (MCP) JSON into the
module's existing dataclasses.

This file never calls an MCP tool itself -- those tools (search_futures,
get_price_snapshot, create_order_instruction, ...) are only callable by an
MCP-connected agent during a live conversation, not by any Python process
(this module included). See goldtrading/CONNECTOR_RUNBOOK.md for the exact
tool-call sequence an agent follows to produce the inputs these functions take,
and goldtrading/STRATEGY.md's "Running via the IBKR Connector" section for the
capability gaps (no spot CMDTY order instruction, no FUT-FUT combo, account
currency, no margin-preview tool) that make this a materially different path
from the TWS connection in goldtrading/ibkr_data.py and goldtrading/execution.py.
"""
from __future__ import annotations

from typing import Any, Optional

from goldtrading.carry import days_to_expiry, round_to_tick
from goldtrading.config import GoldConfig
from goldtrading.models import AccountState, CalendarRecommendation, FuturesQuote, SpotQuote

# COMEX publishes MGC's tick as a fixed exchange spec; the connector's price
# snapshot doesn't expose it, so it's a documented constant here, matching the
# 0.10 fallback goldtrading.carry.round_to_tick already assumes elsewhere.
MGC_MIN_TICK = 0.10


def select_mgc_future_contract(search_contracts_results: list[dict[str, Any]], config: GoldConfig) -> dict[str, Any]:
    """Picks the real futures instrument out of search_contracts(config.futures_symbol) results.

    search_contracts can return multiple unrelated instruments sharing the
    same symbol (confirmed live: searching "MGC" returns both the COMEX
    E-Micro Gold future and an unrelated Vanguard mega-cap ETF on ARCA) --
    selecting on symbol alone risks querying the wrong contract entirely, so
    this also requires the configured futures exchange and a FUT section.
    """
    matches = [
        row
        for row in search_contracts_results
        if row.get("symbol") == config.futures_symbol
        and row.get("exchange") == config.futures_exchange
        and any(section.get("security_type") == "FUT" for section in row.get("sections", []))
    ]
    if not matches:
        raise ValueError(f"no {config.futures_exchange} futures contract named {config.futures_symbol!r} in search_contracts results")
    if len(matches) > 1:
        raise ValueError(f"multiple {config.futures_exchange} futures contracts named {config.futures_symbol!r}; cannot disambiguate")
    return matches[0]


def select_near_far_contracts(search_futures_contracts: list[dict[str, Any]], config: GoldConfig) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Mirrors goldtrading.ibkr_data.futures_quotes' near/far selection rules,
    operating on search_futures' already-fetched term structure instead of a
    live TWS contract-details call. search_futures results are not returned
    in expiry order, so this sorts by contract_month first."""
    dated = sorted(
        (row for row in search_futures_contracts if row.get("last_trading_date")),
        key=lambda row: row["contract_month"],
    )
    near = next(
        (row for row in dated if days_to_expiry(row["last_trading_date"]) >= config.min_days_to_expiry_near),
        None,
    )
    if near is None:
        return None, None
    near_days = days_to_expiry(near["last_trading_date"])
    far = next(
        (row for row in dated if days_to_expiry(row["last_trading_date"]) >= near_days + config.min_days_between_months),
        None,
    )
    return near, far


def _bid_ask(price_snapshot: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """get_price_snapshot's 'bid_ask' field comes back as the hyphenated key
    'bid-ask', and as an empty object when no quote is currently available."""
    quote = price_snapshot.get("bid-ask") or {}
    bid = quote.get("bid")
    ask = quote.get("ask")
    return (float(bid) if bid else None, float(ask) if ask else None)


def futures_quote_from_connector(contract_row: dict[str, Any], price_snapshot: dict[str, Any], min_tick: float = MGC_MIN_TICK) -> FuturesQuote:
    bid, ask = _bid_ask(price_snapshot)
    expiry = contract_row["last_trading_date"]
    return FuturesQuote(
        symbol=contract_row.get("symbol", ""),
        local_symbol=contract_row.get("symbol", ""),
        expiry=expiry,
        bid=bid,
        ask=ask,
        days_to_expiry=days_to_expiry(expiry),
        min_tick=min_tick,
    )


def spot_quote_from_connector(price_snapshot: dict[str, Any], symbol: str) -> SpotQuote:
    bid, ask = _bid_ask(price_snapshot)
    return SpotQuote(symbol=symbol, bid=bid, ask=ask)


def _usd_cash_from_balance_row(row: dict[str, Any]) -> Optional[float]:
    # Field names for get_account_balances are inferred, not yet confirmed
    # against a live call (see STRATEGY.md) -- check each plausible key.
    for key in ("cash_balance", "total_cash_value", "cash"):
        if key in row:
            return float(row[key])
    return None


def account_state_from_connector(account_summary: dict[str, Any], account_balances: list[dict[str, Any]] | None = None) -> AccountState:
    """Prefers a USD row from get_account_balances; falls back to the
    account's base-currency figures from get_account_summary (left
    unconverted) when no USD balance row exists -- callers must surface that
    fallback as a caveat, not treat it as a like-for-like USD figure (see
    CONNECTOR_RUNBOOK.md)."""
    usd_row = next((row for row in (account_balances or []) if row.get("currency") == "USD"), None)
    cash = _usd_cash_from_balance_row(usd_row) if usd_row is not None else None
    if cash is None:
        cash = float(account_summary.get("total_cash_value", 0.0))
    net_liquidation = float(account_summary.get("net_liquidation", cash))
    return AccountState(cash=cash, net_liquidation=net_liquidation)


def build_calendar_spread_instructions(
    recommendation: CalendarRecommendation,
    near_contract_id_ex: str,
    far_contract_id_ex: str,
) -> list[dict[str, Any]]:
    """Builds the two create_order_instruction argument sets for an actionable
    calendar-spread recommendation, matching goldtrading.execution's
    near_action/far_action convention so both execution paths agree on
    direction. Returns [near_leg_args, far_leg_args]; the caller issues two
    separate create_order_instruction calls since the connector doesn't
    support FUT-FUT combos (see STRATEGY.md)."""
    if recommendation.action not in ("SELL_CALENDAR_SPREAD", "BUY_CALENDAR_SPREAD"):
        raise ValueError(f"not an actionable calendar-spread recommendation: {recommendation.action}")
    if recommendation.near_future is None or recommendation.far_future is None:
        raise ValueError("recommendation is missing near/far futures quotes")

    near_price = recommendation.near_future.mid_price or 0.0
    far_price = recommendation.far_future.mid_price or 0.0
    min_tick = recommendation.near_future.min_tick or MGC_MIN_TICK

    # SELL_CALENDAR_SPREAD: buy the (cheap) near leg, sell the (rich) far leg.
    # BUY_CALENDAR_SPREAD: sell the (rich) near leg, buy the (cheap) far leg.
    near_action, far_action = ("BUY", "SELL") if recommendation.action == "SELL_CALENDAR_SPREAD" else ("SELL", "BUY")

    return [
        {
            "contract_id_ex": near_contract_id_ex,
            "side": near_action,
            "quantity": float(recommendation.contracts),
            "order_type": "LIMIT",
            "limit_price": round_to_tick(near_price, min_tick),
            "time_in_force": "DAY",
        },
        {
            "contract_id_ex": far_contract_id_ex,
            "side": far_action,
            "quantity": float(recommendation.contracts),
            "order_type": "LIMIT",
            "limit_price": round_to_tick(far_price, min_tick),
            "time_in_force": "DAY",
        },
    ]
