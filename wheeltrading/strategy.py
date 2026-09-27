"""Pure option-selection rules for a conservative wheel strategy."""
from __future__ import annotations

from typing import Iterable

from wheeltrading.config import WheelConfig
from wheeltrading.models import AccountState, OptionQuote, WheelRecommendation

CONTRACT_MULTIPLIER = 100


def _eligible_quotes(quotes: Iterable[OptionQuote], right: str, config: WheelConfig) -> list[OptionQuote]:
    eligible = []
    for quote in quotes:
        delta = abs(quote.delta) if quote.delta is not None else None
        if (
            quote.right == right
            and config.min_days_to_expiry <= quote.days_to_expiry <= config.max_days_to_expiry
            and delta is not None
            and config.min_delta <= delta <= config.max_delta
            and quote.mid_price is not None
            and quote.mid_price > 0
        ):
            eligible.append(quote)
    return eligible


def _annualized_yield(quote: OptionQuote) -> float:
    premium = quote.mid_price or 0.0
    basis = quote.strike * CONTRACT_MULTIPLIER
    return premium * CONTRACT_MULTIPLIER / basis * 365 / quote.days_to_expiry if basis and quote.days_to_expiry else 0.0


def recommend_wheel_action(config: WheelConfig, account: AccountState, quotes: Iterable[OptionQuote]) -> WheelRecommendation:
    if account.stock_qty >= CONTRACT_MULTIPLIER:
        action = "SELL_COVERED_CALL"
        contracts = min(config.contracts_per_trade, account.stock_qty // CONTRACT_MULTIPLIER)
        candidates = _eligible_quotes(quotes, "C", config)
    else:
        action = "SELL_CASH_SECURED_PUT"
        contracts = config.contracts_per_trade
        candidates = _eligible_quotes(quotes, "P", config)

    candidates.sort(key=lambda quote: (_annualized_yield(quote), -(abs(quote.delta or 0))), reverse=True)
    for quote in candidates:
        collateral = quote.strike * CONTRACT_MULTIPLIER * contracts
        yield_rate = _annualized_yield(quote)
        if action == "SELL_CASH_SECURED_PUT":
            if collateral > account.cash:
                continue
            if collateral > account.net_liquidation * config.max_allocation_pct:
                continue
        if yield_rate < config.min_annualized_yield:
            continue
        premium = (quote.mid_price or 0.0) * CONTRACT_MULTIPLIER * contracts
        return WheelRecommendation(
            symbol=config.symbol,
            action=action,
            contracts=contracts,
            contract=quote,
            premium_credit=premium,
            collateral_required=collateral if action == "SELL_CASH_SECURED_PUT" else 0.0,
            annualized_yield=yield_rate,
            reasons=["option meets DTE, delta, premium, and allocation constraints"],
        )

    return WheelRecommendation(
        symbol=config.symbol,
        action="HOLD",
        contracts=0,
        contract=None,
        premium_credit=None,
        collateral_required=0.0,
        annualized_yield=None,
        reasons=["no option contract satisfies wheel entry constraints"],
    )