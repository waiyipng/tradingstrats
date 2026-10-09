"""Strike selection, payoff math, and suggested exit plan for a bull call spread."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.models import (
    AccountState,
    BullCallSpreadRecommendation,
    CallLeg,
    ExitPlan,
    PayoffPoint,
)


def _has_tradable_quote(leg: CallLeg, max_relative_spread: float) -> bool:
    if leg.bid is None or leg.ask is None or leg.bid <= 0 or leg.ask <= 0:
        return False
    return (leg.ask - leg.bid) / leg.ask <= max_relative_spread


def _net_debit(long_leg: CallLeg, short_leg: CallLeg) -> float | None:
    long_price = long_leg.ask or long_leg.mid_price
    short_price = short_leg.bid or short_leg.mid_price
    if long_price is None or short_price is None:
        return None
    return round(long_price - short_price, 2)


def select_spread(
    config: BullCallSpreadConfig, spot: float, target_price: float, legs: list[CallLeg]
) -> tuple[CallLeg, CallLeg] | None:
    """Pick the long/short strike pair maximizing return-on-debit within the width range.

    Long leg: the call closest to (but not above) the current spot price.
    Short leg: a call at/above the target price, within the configured width range.
    """
    by_strike = {leg.strike: leg for leg in legs}
    strikes = sorted(by_strike)
    if not strikes:
        return None

    tradable_strikes = [strike for strike in strikes if _has_tradable_quote(by_strike[strike], config.max_relative_bid_ask_spread)]
    long_candidates = [strike for strike in tradable_strikes if strike <= spot]
    if not long_candidates and not tradable_strikes:
        return None
    long_strike = max(long_candidates) if long_candidates else min(tradable_strikes)

    min_short = long_strike + config.min_width_pct * spot
    max_short = long_strike + config.max_width_pct * spot
    short_candidates = [
        strike
        for strike in tradable_strikes
        if strike > long_strike and min_short <= strike <= max_short and strike >= target_price
    ]
    if not short_candidates:
        # No strike at/above target within the width band; fall back to the
        # widest allowed strike below target so a spread can still be priced.
        short_candidates = [strike for strike in tradable_strikes if long_strike < strike <= max_short]
    if not short_candidates:
        return None

    best = None
    best_return = -math.inf
    for short_strike in short_candidates:
        long_leg = by_strike[long_strike]
        short_leg = by_strike[short_strike]
        debit = _net_debit(long_leg, short_leg)
        if debit is None or debit <= 0:
            continue
        width = short_strike - long_strike
        max_profit = width - debit
        return_on_debit = max_profit / debit
        if return_on_debit > best_return:
            best_return = return_on_debit
            best = (long_leg, short_leg)
    return best


def build_payoff_ladder(long_strike: float, short_strike: float, net_debit: float, contracts: int, target_price: float, spot: float) -> list[PayoffPoint]:
    def pl_at(price: float) -> float:
        intrinsic = max(0.0, min(price, short_strike) - long_strike)
        return round((intrinsic - net_debit) * 100 * contracts, 2)

    prices = sorted(
        {
            round(spot * 0.90, 2): "spot -10%",
            round(spot * 0.95, 2): "spot -5%",
            round(spot, 2): "spot (current)",
            long_strike: "long strike",
            short_strike: "short strike",
            round(target_price, 2): "target price",
            round(target_price * 1.05, 2): "target +5%",
        }.items()
    )
    return [PayoffPoint(price=price, label=label, profit_loss=pl_at(price)) for price, label in prices]


def build_exit_plan(config: BullCallSpreadConfig, net_debit: float, expiry: str) -> ExitPlan:
    expiry_date = datetime.strptime(expiry, "%Y%m%d").date()
    exit_by = expiry_date - timedelta(days=config.exit_days_before_expiry)
    stop_value = round(net_debit * config.stop_loss_pct_of_debit, 2)
    return ExitPlan(
        stop_loss_debit_value=stop_value,
        stop_loss_pct_of_debit=config.stop_loss_pct_of_debit,
        exit_by_date=exit_by.isoformat(),
        notes=[
            f"Close the spread (sell the long call, buy back the short call) if its market value falls to "
            f"${stop_value:.2f} or below (={config.stop_loss_pct_of_debit:.0%} of the ${net_debit:.2f} entry debit).",
            f"Close the spread by {exit_by.isoformat()} ({config.exit_days_before_expiry} days before expiry) "
            "regardless of P&L to avoid late-cycle theta decay and assignment risk on the short leg.",
            "A vertical call spread has no single stock stop-loss price; the stop is expressed on the "
            "spread's own premium since max loss is already capped at the entry debit.",
        ],
    )


def evaluate_bull_call_spread(
    config: BullCallSpreadConfig,
    account: AccountState,
    spot: float,
    expiry: str,
    legs: list[CallLeg],
    target_price: float,
    target_date: str,
    amount: float,
) -> BullCallSpreadRecommendation:
    reasons: list[str] = []
    selection = select_spread(config, spot, target_price, legs)
    if selection is None:
        reasons.append("no viable long/short call pair found within the configured width range")
        return BullCallSpreadRecommendation(
            action="HOLD", symbol=config.symbol, target_price=target_price, target_date=target_date,
            expiry=expiry, long_leg=None, short_leg=None, contracts=0, net_debit=None, max_profit=None,
            max_loss=None, breakeven=None, return_on_debit_pct=None, payoff_ladder=[], exit_plan=None, reasons=reasons,
        )

    long_leg, short_leg = selection
    net_debit = _net_debit(long_leg, short_leg)
    if net_debit is None or net_debit <= 0:
        reasons.append("no valid net debit could be computed from live bid/ask quotes")
        return BullCallSpreadRecommendation(
            action="HOLD", symbol=config.symbol, target_price=target_price, target_date=target_date,
            expiry=expiry, long_leg=long_leg, short_leg=short_leg, contracts=0, net_debit=net_debit,
            max_profit=None, max_loss=None, breakeven=None, return_on_debit_pct=None, payoff_ladder=[],
            exit_plan=None, reasons=reasons,
        )

    cost_per_contract = net_debit * 100 + config.round_trip_cost_per_contract
    contracts = max(0, math.floor(amount / cost_per_contract))
    if contracts == 0:
        reasons.append(f"${amount:.2f} is insufficient to buy even one contract at a ${net_debit:.2f} net debit")
        return BullCallSpreadRecommendation(
            action="HOLD", symbol=config.symbol, target_price=target_price, target_date=target_date,
            expiry=expiry, long_leg=long_leg, short_leg=short_leg, contracts=0, net_debit=net_debit,
            max_profit=None, max_loss=None, breakeven=None, return_on_debit_pct=None, payoff_ladder=[],
            exit_plan=None, reasons=reasons,
        )

    notional = cost_per_contract * contracts
    if notional > config.max_notional_pct_of_excess_liquidity * account.excess_liquidity:
        reasons.append(
            f"requested notional (${notional:.2f}) exceeds {config.max_notional_pct_of_excess_liquidity:.0%} of excess liquidity"
        )
        return BullCallSpreadRecommendation(
            action="HOLD", symbol=config.symbol, target_price=target_price, target_date=target_date,
            expiry=expiry, long_leg=long_leg, short_leg=short_leg, contracts=0, net_debit=net_debit,
            max_profit=None, max_loss=None, breakeven=None, return_on_debit_pct=None, payoff_ladder=[],
            exit_plan=None, reasons=reasons,
        )

    width = short_leg.strike - long_leg.strike
    max_profit = round((width - net_debit) * 100 * contracts, 2)
    max_loss = round(net_debit * 100 * contracts, 2)
    breakeven = round(long_leg.strike + net_debit, 2)
    return_on_debit_pct = round(((width - net_debit) / net_debit) * 100, 2)

    reasons.append(
        f"bought {long_leg.strike} call / sold {short_leg.strike} call expiring {expiry} "
        f"({contracts} contract(s)) for a ${net_debit:.2f} net debit, targeting ${target_price:.2f} by {target_date}"
    )

    return BullCallSpreadRecommendation(
        action="BUY_BULL_CALL_SPREAD",
        symbol=config.symbol,
        target_price=target_price,
        target_date=target_date,
        expiry=expiry,
        long_leg=long_leg,
        short_leg=short_leg,
        contracts=contracts,
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=breakeven,
        return_on_debit_pct=return_on_debit_pct,
        payoff_ladder=build_payoff_ladder(long_leg.strike, short_leg.strike, net_debit, contracts, target_price, spot),
        exit_plan=build_exit_plan(config, net_debit, expiry),
        reasons=reasons,
    )
