"""Pure trend-signal math shared by the backtest and the live trader, so live
behaviour is exactly the behaviour that was researched. No I/O here."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from btctrend.config import BtcTrendConfig
from btctrend.models import SignalVote, TrendSignal

DAYS_PER_YEAR = 365  # bitcoin trades every day


def _donchian_state(bars: pd.DataFrame, entry: int, exit_: int) -> pd.Series:
    """Long after closing above the prior `entry`-day high, flat after closing below
    the prior `exit_`-day low, otherwise keep the previous state."""
    upper = bars["high"].rolling(entry).max().shift(1)
    lower = bars["low"].rolling(exit_).min().shift(1)
    state = pd.Series(np.nan, index=bars.index)
    state[bars["close"] > upper] = 1.0
    state[bars["close"] < lower] = 0.0
    return state.ffill().fillna(0.0)


def signal_votes(bars: pd.DataFrame, config: BtcTrendConfig) -> pd.DataFrame:
    """One 0/1 column per ensemble member. `bars` needs high, low, close columns."""
    close = bars["close"]
    votes: dict[str, pd.Series] = {}
    for n in config.sma_lookbacks:
        votes[f"close>sma{n}"] = (close > close.rolling(n).mean()).astype(float)
    for fast, slow in config.sma_crossovers:
        votes[f"sma{fast}>sma{slow}"] = (close.rolling(fast).mean() > close.rolling(slow).mean()).astype(float)
    for n in config.momentum_lookbacks:
        votes[f"mom{n}>0"] = (close.pct_change(n) > 0).astype(float)
    for entry, exit_ in config.donchian_channels:
        votes[f"donchian{entry}/{exit_}"] = _donchian_state(bars, entry, exit_)
    return pd.DataFrame(votes, index=bars.index)


def realized_vol(close: pd.Series, window: int) -> pd.Series:
    return close.pct_change().rolling(window).std() * math.sqrt(DAYS_PER_YEAR)


def target_exposure_series(bars: pd.DataFrame, config: BtcTrendConfig) -> pd.Series:
    """Desired fraction of the sleeve held long at each bar's close."""
    score = signal_votes(bars, config).mean(axis=1)
    vol_scalar = (config.vol_target_annual / realized_vol(bars["close"], config.vol_window_days)).clip(upper=config.max_exposure)
    return (score * vol_scalar).fillna(0.0).clip(lower=0.0, upper=config.max_exposure)


def average_true_range(bars: pd.DataFrame, window: int) -> pd.Series:
    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(window).mean()


def reentry_breakout_level(close: pd.Series, days: int) -> pd.Series:
    """Prior N-day highest close; a close above it lifts a stop-out lock."""
    return close.rolling(days).max().shift(1)


def trailing_stop_price(peak_close: float, atr: float, multiple: float) -> float:
    return peak_close - multiple * atr


def apply_band(target: float, held: float, band: float) -> float:
    """New held exposure: exits always execute; other changes only beyond the band."""
    if target <= 0 and held > 0:
        return 0.0
    if abs(target - held) > band:
        return target
    return held


def min_history_bars(config: BtcTrendConfig) -> int:
    longest = max(
        [*config.sma_lookbacks, *(slow for _, slow in config.sma_crossovers), *config.momentum_lookbacks,
         *(max(entry, exit_) for entry, exit_ in config.donchian_channels), config.vol_window_days]
    )
    return longest + 1


def latest_signal(bars: pd.DataFrame, config: BtcTrendConfig) -> TrendSignal:
    """Signal snapshot at the last (completed) bar, with each member's inputs for audit."""
    if len(bars) < min_history_bars(config):
        raise RuntimeError(f"need at least {min_history_bars(config)} daily bars, got {len(bars)}")

    close = bars["close"]
    last = float(close.iloc[-1])
    votes_frame = signal_votes(bars, config)
    latest_votes = votes_frame.iloc[-1]

    details: dict[str, str] = {}
    for n in config.sma_lookbacks:
        sma = float(close.rolling(n).mean().iloc[-1])
        details[f"close>sma{n}"] = f"close {last:,.0f} vs SMA{n} {sma:,.0f} ({(last / sma - 1) * 100:+.1f}%)"
    for fast, slow in config.sma_crossovers:
        fast_value = float(close.rolling(fast).mean().iloc[-1])
        slow_value = float(close.rolling(slow).mean().iloc[-1])
        details[f"sma{fast}>sma{slow}"] = f"SMA{fast} {fast_value:,.0f} vs SMA{slow} {slow_value:,.0f}"
    for n in config.momentum_lookbacks:
        details[f"mom{n}>0"] = f"{n}-day return {float(close.pct_change(n).iloc[-1]) * 100:+.1f}%"
    for entry, exit_ in config.donchian_channels:
        upper = float(bars["high"].rolling(entry).max().shift(1).iloc[-1])
        lower = float(bars["low"].rolling(exit_).min().shift(1).iloc[-1])
        details[f"donchian{entry}/{exit_}"] = f"breakout above {upper:,.0f}, exit below {lower:,.0f}"

    vol = float(realized_vol(close, config.vol_window_days).iloc[-1])
    vol_scalar = min(config.max_exposure, config.vol_target_annual / vol) if vol > 0 else 0.0
    score = float(latest_votes.mean())
    return TrendSignal(
        bar_date=bars.index[-1].strftime("%Y-%m-%d"),
        close=round(last, 2),
        votes=[SignalVote(name=name, long=bool(latest_votes[name]), detail=details[name]) for name in votes_frame.columns],
        score=round(score, 4),
        realized_vol_annual=round(vol, 4),
        vol_scalar=round(vol_scalar, 4),
        target_exposure=round(min(config.max_exposure, max(0.0, score * vol_scalar)), 4),
        return_30d_pct=round(float(close.pct_change(30).iloc[-1]) * 100, 2),
        drawdown_from_high_pct=round((last / float(close.max()) - 1) * 100, 2),
        atr=round(float(average_true_range(bars, config.atr_window_days).iloc[-1]), 2),
        reentry_breakout_level=round(float(reentry_breakout_level(close, config.reentry_breakout_days).iloc[-1]), 2),
    )
