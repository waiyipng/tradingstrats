"""Turns the ensemble signal into a sized, risk-gated BTC rebalance recommendation.

Exits come from three independent sources:
- signal exits: the ensemble target falls (votes turn flat or volatility rises);
- risk exit: a trailing stop at the highest close since entry minus N x ATR,
  checked every cycle against the live bid. A stop-out keeps the strategy flat
  until the close breaks above the prior 20-day high;
- profit taking: once a daily close is +50% above the trade's entry close, the
  position is trimmed by a third once, and the rest rides the trailing stop.
If the daily data is stale, exposure may be reduced but never increased.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from btctrend.config import BtcTrendConfig
from btctrend.models import AccountState, BtcQuote, RebalanceRecommendation, TrendSignal
from btctrend.signals import apply_band, trailing_stop_price


def round_down(qty: float, increment: float) -> float:
    if increment <= 0:
        return qty
    return round(math.floor(qty / increment + 1e-9) * increment, 8)


def _hold(signal: TrendSignal, state: dict[str, Any], sleeve: float, current_qty: float, reasons: list[str]) -> RebalanceRecommendation:
    """No-op that leaves every piece of persisted state exactly as it was."""
    held = float(state["held_exposure"])
    return RebalanceRecommendation(
        action="HOLD", signal_target_exposure=signal.target_exposure, held_exposure_before=held, new_held_exposure=held,
        sleeve_usd=round(sleeve, 2), current_qty=current_qty, target_qty=float(state["target_qty"]), order_qty=0.0,
        limit_price=None, order_notional=0.0, reasons=reasons,
        peak_close=float(state["peak_close"]), reentry_locked=bool(state["stop_locked"]),
        entry_price=float(state["entry_price"]), profit_taken=bool(state["profit_taken"]),
    )


def evaluate_rebalance(
    config: BtcTrendConfig,
    signal: TrendSignal,
    account: AccountState,
    quote: BtcQuote,
    state: dict[str, Any],
    account_btc_qty: float,
    size_increment: float = 0.0001,
    data_stale: bool = False,
) -> RebalanceRecommendation:
    sleeve = config.max_allocation_pct_of_excess_liquidity * account.excess_liquidity
    # Strategy-owned quantity, never more than the account actually holds.
    current_qty = max(0.0, min(float(state["btc_qty"]), account_btc_qty))
    reasons = [
        f"quote source {quote.source}: bid {quote.bid} / ask {quote.ask}",
        f"ensemble score {signal.score:.2f} ({sum(v.long for v in signal.votes)}/{len(signal.votes)} long votes) "
        f"x vol scalar {signal.vol_scalar:.2f} (30d vol {signal.realized_vol_annual:.0%} vs {config.vol_target_annual:.0%} target) "
        f"= target exposure {signal.target_exposure:.0%} of the sleeve"
    ]

    price = quote.mid_price
    if price is None or not quote.bid or not quote.ask:
        return _hold(signal, state, sleeve, current_qty, reasons + ["no two-sided IBKR BTC quote; nothing submitted"])
    deviation = abs(price / signal.close - 1)
    if deviation > config.max_quote_deviation_pct:
        return _hold(signal, state, sleeve, current_qty, reasons + [f"IBKR quote {price:,.2f} deviates {deviation:.0%} from last close {signal.close:,.2f}; data rejected"])
    if sleeve <= 0:
        return _hold(signal, state, sleeve, current_qty, reasons + ["net liquidation unavailable; sleeve is zero"])

    # --- Risk exit: trailing ATR stop and the post-stop re-entry lock.
    locked = bool(state["stop_locked"])
    peak = max(float(state["peak_close"]), signal.close) if current_qty > 0 else 0.0
    stop_price: Optional[float] = round(trailing_stop_price(peak, signal.atr, config.trailing_stop_atr_multiple), 2) if current_qty > 0 else None
    stop_triggered = stop_price is not None and quote.bid <= stop_price
    if stop_triggered:
        locked = True
        reasons.append(f"TRAILING STOP: bid {quote.bid:,.2f} <= stop {stop_price:,.2f} (peak close {peak:,.0f} - {config.trailing_stop_atr_multiple:g} x ATR {signal.atr:,.0f}); exiting")
    elif stop_price is not None:
        reasons.append(f"trailing stop {stop_price:,.2f} ({(stop_price / quote.bid - 1) * 100:+.1f}% from bid; peak close {peak:,.0f} - {config.trailing_stop_atr_multiple:g} x ATR {signal.atr:,.0f})")
    if locked and not stop_triggered:
        if signal.close > signal.reentry_breakout_level:
            locked = False
            reasons.append(f"stop-out lock lifted: close {signal.close:,.0f} broke above the prior {config.reentry_breakout_days}-day high {signal.reentry_breakout_level:,.0f}")
        else:
            reasons.append(f"stopped out earlier; flat until a close above {signal.reentry_breakout_level:,.0f} (prior {config.reentry_breakout_days}-day high)")
    effective_target = 0.0 if locked else signal.target_exposure

    # --- Profit taking: one-time trim once the close is far enough above entry.
    entry_price = float(state["entry_price"])
    profit_taken = bool(state["profit_taken"]) and current_qty > 0
    if current_qty > 0 and entry_price > 0 and not profit_taken and signal.close >= entry_price * (1 + config.profit_take_gain_pct):
        profit_taken = True
        reasons.append(f"PROFIT TAKE: close {signal.close:,.0f} is {signal.close / entry_price - 1:+.0%} vs entry {entry_price:,.0f}; trimming {config.profit_take_fraction:.0%} and letting the rest ride")
    exposure_cap = 1 - config.profit_take_fraction if profit_taken else config.max_exposure
    effective_target = min(effective_target, exposure_cap)

    held_before = float(state["held_exposure"])
    if data_stale and effective_target > held_before:
        effective_target = held_before
        reasons.append(f"daily data is more than {config.max_bar_age_days} day(s) old; increases blocked, exits still allowed")
    new_held = min(apply_band(effective_target, held_before, config.rebalance_band), exposure_cap)
    if new_held != held_before:
        target_qty = round_down(new_held * sleeve / price, size_increment)
        reasons.append(f"target moved from {held_before:.0%} to {new_held:.0%} (beyond the {config.rebalance_band:.0%} band, an exit, or a trim)")
        if held_before == 0 and new_held > 0:
            peak = entry_price = signal.close  # new entry: stop and profit target measure from here
            profit_taken = False
    else:
        # Keep working toward the committed quantity (e.g. after a partial IOC fill)
        # without re-sizing for price drift.
        target_qty = float(state["target_qty"])
        reasons.append(f"target {effective_target:.0%} within the {config.rebalance_band:.0%} band of held {held_before:.0%}")
    if new_held == 0 and target_qty == 0 and current_qty == 0:
        peak, entry_price, profit_taken = 0.0, 0.0, False
    stop_after_trade = trailing_stop_price(peak, signal.atr, config.trailing_stop_atr_multiple) if target_qty > 0 else None
    risk_usd = round(target_qty * max(0.0, price - stop_after_trade), 2) if stop_after_trade is not None else 0.0
    risk = {
        "peak_close": peak, "stop_price": stop_price, "stop_triggered": stop_triggered, "reentry_locked": locked,
        "entry_price": entry_price, "profit_taken": profit_taken,
        "risk_at_stop_usd": risk_usd, "risk_at_stop_pct_of_net_liq": round(risk_usd / account.net_liquidation, 4),
        "stop_price_if_filled": round(stop_after_trade, 2) if stop_after_trade is not None else None,
    }

    delta = round_down(abs(target_qty - current_qty), size_increment)
    if delta * price < config.min_order_usd:
        return RebalanceRecommendation(
            action="HOLD", signal_target_exposure=signal.target_exposure, held_exposure_before=held_before, new_held_exposure=new_held,
            sleeve_usd=round(sleeve, 2), current_qty=current_qty, target_qty=target_qty, order_qty=0.0, limit_price=None,
            order_notional=0.0, reasons=reasons + [f"position already at target ({current_qty:.4f} BTC)"], **risk,
        )

    if target_qty > current_qty:
        action = "BUY"
        limit_price = round(quote.ask * (1 + config.limit_offset_pct), 2)
        spendable = account.cash - config.min_cash_reserve_pct * account.net_liquidation
        affordable = round_down(max(0.0, spendable) / limit_price, size_increment)
        if affordable < delta:
            reasons.append(f"order reduced from {delta:.4f} to {affordable:.4f} BTC by available cash after the {config.min_cash_reserve_pct:.0%} reserve")
            delta = affordable
        if delta * limit_price < config.min_order_usd:
            return _hold(signal, state, sleeve, current_qty, reasons + ["insufficient cash for a minimum-size buy"])
    else:
        action = "SELL"
        limit_price = round(quote.bid * (1 - config.limit_offset_pct), 2)

    reasons.append(f"{action} {delta:.4f} BTC toward {target_qty:.4f} BTC ({new_held:.0%} of a ${sleeve:,.0f} sleeve)")
    return RebalanceRecommendation(
        action=action, signal_target_exposure=signal.target_exposure, held_exposure_before=held_before, new_held_exposure=new_held,
        sleeve_usd=round(sleeve, 2), current_qty=current_qty, target_qty=target_qty, order_qty=delta,
        limit_price=limit_price, order_notional=round(delta * limit_price, 2), reasons=reasons, **risk,
    )
