"""Reproducible BTC trend-following research backtest.

Trades on the bar after the signal (no look-ahead), charges a per-side cost on
every exposure change, and reports in-sample, out-of-sample, and full-period
statistics against buy-and-hold. Writes data/backtest_report.json for the
dashboard.

    /usr/local/bin/python3 -m btctrend.backtest [--cost 0.0025]
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from newstrading.common import save_json, utcnow_iso
from btctrend.config import BTC_CONFIG, BtcTrendConfig
from btctrend.history import fetch_daily_bars
from btctrend.signals import (
    DAYS_PER_YEAR,
    apply_band,
    average_true_range,
    reentry_breakout_level,
    signal_votes,
    target_exposure_series,
    trailing_stop_price,
)

REPORT_PATH = Path(__file__).resolve().parent / "data" / "backtest_report.json"


def banded_positions(targets: pd.Series, band: float) -> pd.Series:
    held, out = 0.0, []
    for target in targets.to_numpy():
        held = apply_band(float(target), held, band)
        out.append(held)
    return pd.Series(out, index=targets.index)


def strategy_returns(close: pd.Series, held: pd.Series, cost_per_side: float) -> tuple[pd.Series, pd.Series]:
    """Daily net returns and the position actually carried through each day."""
    position = held.shift(1).fillna(0.0)  # decided at yesterday's close, held today
    returns = position * close.pct_change().fillna(0.0) - position.diff().abs().fillna(0.0) * cost_per_side
    return returns, position


def simulate_with_stop(
    bars: pd.DataFrame, config: BtcTrendConfig, cost_per_side: float, profit_taking: bool = True
) -> tuple[pd.Series, pd.Series]:
    """The live rules including the trailing ATR stop and the profit trim. The stop is
    tested against each day's low and fills at the stop, or at the open if the market
    gaps through it. After a stop-out the strategy stays flat until a close above the
    prior N-day high. Once a close is profit_take_gain_pct above the entry close,
    exposure is capped at (1 - profit_take_fraction) for the rest of the trade."""
    opens, lows, closes = (bars[column].to_numpy() for column in ("open", "low", "close"))
    targets = target_exposure_series(bars, config).to_numpy()
    atr = average_true_range(bars, config.atr_window_days).to_numpy()
    breakout = reentry_breakout_level(bars["close"], config.reentry_breakout_days).to_numpy()
    returns, positions = np.zeros(len(closes)), np.zeros(len(closes))
    held, peak, stop, locked = 0.0, 0.0, None, False
    entry, cap = 0.0, config.max_exposure
    for i in range(1, len(closes)):
        positions[i] = held  # decided at yesterday's close
        if held > 0 and stop is not None and lows[i] <= stop:
            fill = min(opens[i], stop)
            returns[i] = held * (fill / closes[i - 1] - 1) - held * cost_per_side
            held, stop, locked = 0.0, None, True
        else:
            returns[i] = held * (closes[i] / closes[i - 1] - 1)

        if locked and closes[i] > breakout[i]:
            locked = False
        if profit_taking and held > 0 and cap == config.max_exposure and closes[i] >= entry * (1 + config.profit_take_gain_pct):
            cap = 1 - config.profit_take_fraction
        target = min(0.0 if locked else float(targets[i]), cap)
        new_held = min(apply_band(target, held, config.rebalance_band), cap)
        returns[i] -= abs(new_held - held) * cost_per_side
        if held == 0 and new_held > 0:
            peak = entry = closes[i]
            cap = config.max_exposure
        held = new_held
        if held > 0:
            peak = max(peak, closes[i])
            stop = trailing_stop_price(peak, atr[i], config.trailing_stop_atr_multiple)
        else:
            stop = None
    return pd.Series(returns, index=bars.index), pd.Series(positions, index=bars.index)


def performance(returns: pd.Series, position: pd.Series) -> dict[str, float]:
    equity = (1 + returns).cumprod()
    years = len(returns) / DAYS_PER_YEAR
    cagr = equity.iloc[-1] ** (1 / years) - 1
    std = returns.std()
    drawdown = (equity / equity.cummax() - 1).min()
    return {
        "cagr_pct": round(cagr * 100, 1),
        "sharpe": round(returns.mean() / std * math.sqrt(DAYS_PER_YEAR), 2) if std > 0 else 0.0,
        "max_drawdown_pct": round(drawdown * 100, 1),
        "calmar": round(cagr / abs(drawdown), 2) if drawdown < 0 else 0.0,
        "avg_exposure_pct": round(position.mean() * 100, 1),
        "turnover_per_year": round(position.diff().abs().sum() / years, 1),
    }


def _period(returns: pd.Series, position: pd.Series, start: str | None, end: str | None) -> dict[str, float]:
    return performance(returns[start:end], position[start:end])


def run_backtest(config: BtcTrendConfig, bars: pd.DataFrame, cost_per_side: float) -> dict[str, Any]:
    close = bars["close"]
    in_sample_end = (pd.Timestamp(config.backtest_oos_start) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    variants = {
        "strategy": simulate_with_stop(bars, config, cost_per_side),
        "no_profit_taking": simulate_with_stop(bars, config, cost_per_side, profit_taking=False),
        "signal_exits_only": strategy_returns(close, banded_positions(target_exposure_series(bars, config), config.rebalance_band), cost_per_side),
        "buy_and_hold": strategy_returns(close, pd.Series(1.0, index=bars.index), 0.0),
    }
    results: dict[str, Any] = {}
    for name, (returns, position) in variants.items():
        results[name] = {
            "in_sample": _period(returns, position, None, in_sample_end),
            "out_of_sample": _period(returns, position, config.backtest_oos_start, None),
            "full": _period(returns, position, None, None),
            "yearly_returns_pct": {str(year): round(value * 100, 1) for year, value in ((1 + returns).groupby(returns.index.year).prod() - 1).items()},
        }

    member_rows = {}
    for name, votes in signal_votes(bars, config).items():
        returns, position = strategy_returns(close, votes, cost_per_side)
        member_rows[name] = {"out_of_sample": _period(returns, position, config.backtest_oos_start, None)}

    return {
        "generated_at": utcnow_iso(),
        "data": {"symbol": config.history_symbol, "first_bar": bars.index[0].strftime("%Y-%m-%d"), "last_bar": bars.index[-1].strftime("%Y-%m-%d"), "bars": len(bars)},
        "assumptions": {
            "cost_per_side": cost_per_side,
            "in_sample": f"{bars.index[0]:%Y-%m-%d} to {in_sample_end}",
            "out_of_sample": f"{config.backtest_oos_start} onward",
            "execution": "position decided at a daily close is held from the next bar; no look-ahead",
            "vol_target_annual": config.vol_target_annual,
            "rebalance_band": config.rebalance_band,
            "profit_taking": f"trim {config.profit_take_fraction:.0%} once a close is {config.profit_take_gain_pct:+.0%} vs entry",
            "trailing_stop": f"{config.trailing_stop_atr_multiple:g} x {config.atr_window_days}-day ATR below the highest close since entry; re-enter above the prior {config.reentry_breakout_days}-day high",
        },
        "results": results,
        "ensemble_members": member_rows,
    }


def _print_row(label: str, stats: dict[str, float]) -> None:
    print(f"  {label:15s} CAGR {stats['cagr_pct']:6.1f}%  Sharpe {stats['sharpe']:5.2f}  MaxDD {stats['max_drawdown_pct']:6.1f}%  "
          f"exposure {stats['avg_exposure_pct']:5.1f}%  turnover/yr {stats['turnover_per_year']:5.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the BTC trend-following ensemble against buy-and-hold.")
    parser.add_argument("--cost", type=float, default=BTC_CONFIG.backtest_cost_per_side, help="per-side cost as a fraction (default 0.0025)")
    args = parser.parse_args()

    bars = fetch_daily_bars(BTC_CONFIG.history_symbol, start=BTC_CONFIG.backtest_start)
    report = run_backtest(BTC_CONFIG, bars, args.cost)
    save_json(REPORT_PATH, report)

    print(f"BTC-USD daily {report['data']['first_bar']} to {report['data']['last_bar']} ({report['data']['bars']} bars), cost {args.cost:.2%}/side")
    for name, result in report["results"].items():
        print(name)
        for period in ("in_sample", "out_of_sample", "full"):
            _print_row(period, result[period])
    print("ensemble members, out of sample:")
    for name, row in report["ensemble_members"].items():
        _print_row(name, row["out_of_sample"])
    print(f"-> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
