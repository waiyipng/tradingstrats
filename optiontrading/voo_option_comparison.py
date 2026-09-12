"""Compare 10%-OTM covered calls and cash-secured puts on VOO.

This uses the same historical-price and Black-Scholes conventions as
covered_call_report.py. Option prices are estimates, not historical quotes.
"""

import argparse
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from covered_call_report import (
    bs_call_price,
    get_dividend_yield,
    get_iv_estimate,
    get_price_history,
)


def bs_put_price(S, K, T, r, q, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def cycle_end_index(prices, idx, cycle_days):
    target_date = prices.index[idx] + timedelta(days=cycle_days)
    next_idx = min(prices.index.searchsorted(target_date), len(prices) - 1)
    return max(next_idx, idx + 1)


def run_short_put(prices, cycle_days, otm_pct, r, q, shares=100, iv_lookback=30):
    """Backtest repeated cash-secured puts, reporting P&L versus starting cash."""
    initial_capital = shares * float(prices.iloc[0])
    cash = initial_capital
    dates = prices.index
    idx = 0
    log = []

    while idx < len(prices) - 1:
        S0 = float(prices.iloc[idx])
        strike = S0 * (1 - otm_pct / 100)
        sigma = get_iv_estimate(prices, idx, lookback=iv_lookback)
        premium = bs_put_price(S0, strike, cycle_days / 365, r, q, sigma) * shares
        next_idx = cycle_end_index(prices, idx, cycle_days)
        S1 = float(prices.iloc[next_idx])
        intrinsic_loss = max(strike - S1, 0.0) * shares
        cash += premium - intrinsic_loss

        log.append({
            "cycle_start": dates[idx].date(),
            "spot_start": round(S0, 2),
            "strike": round(strike, 2),
            "iv_used_pct": round(sigma * 100, 1),
            "premium_collected": round(premium, 2),
            "cycle_end": dates[next_idx].date(),
            "spot_end": round(S1, 2),
            "intrinsic_loss": round(intrinsic_loss, 2),
            "put_expired_itm": intrinsic_loss > 0,
        })
        idx = next_idx

    return cash - initial_capital, pd.DataFrame(log)


def print_comparison(ticker, prices, cycle_days, otm_pct, shares, cc_pnl, put_pnl, q, r):
    initial_capital = shares * float(prices.iloc[0])
    buy_hold_pnl = shares * (float(prices.iloc[-1]) - float(prices.iloc[0]))
    results = [
        ("Covered call", cc_pnl),
        ("Cash-secured put", put_pnl),
        ("Buy & hold VOO", buy_hold_pnl),
    ]

    print("=" * 64)
    print(f"  {ticker}: 3-YEAR OPTION STRATEGY COMPARISON")
    print("=" * 64)
    print(f"  Period:          {prices.index[0].date()} to {prices.index[-1].date()}")
    print(f"  Starting capital: ${initial_capital:,.2f} ({shares} shares)")
    print(f"  Option setup:    {otm_pct:.0f}% OTM, {cycle_days}-day cycles")
    print(f"  VOO start/end:   ${prices.iloc[0]:.2f} / ${prices.iloc[-1]:.2f}")
    print("-" * 64)
    print(f"  {'Strategy':<24}{'P&L':>16}{'Return':>14}")
    for name, pnl in results:
        print(f"  {name:<24}${pnl:>14,.2f}{pnl / initial_capital * 100:>13.1f}%")
    print("-" * 64)
    winner = max(results, key=lambda result: result[1])
    print(f"  Best result: {winner[0]} (${winner[1]:,.2f} P&L)")
    print("=" * 64)
    print("  Notes: option premiums use Black-Scholes with realized volatility as an IV proxy.")
    print(f"  Risk-free rate: {r:.2%}; dividend yield used for options: {q:.2%}")
    print("  Put model is cash-settled at each cycle expiration; no fees, slippage, or early assignment.")


def main():
    parser = argparse.ArgumentParser(description="Compare 10%-OTM VOO options with buy-and-hold.")
    parser.add_argument("--ticker", default="VOO")
    parser.add_argument("--start", default=(datetime.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d"))
    parser.add_argument("--end", default=datetime.today().strftime("%Y-%m-%d"))
    parser.add_argument("--otm-pct", type=float, default=10.0)
    parser.add_argument("--cycle-days", type=int, default=30)
    parser.add_argument("--shares", type=int, default=100)
    parser.add_argument("--risk-free-rate", type=float, default=0.04)
    parser.add_argument("--dividend-yield", type=float, default=None)
    parser.add_argument("--iv-lookback", type=int, default=30)
    parser.add_argument("--put-csv-out", default="voo_short_put_cycles.csv")
    args = parser.parse_args()

    print(f"Fetching {args.ticker} prices from {args.start} to {args.end}...\n")
    prices = get_price_history(args.ticker, args.start, args.end)
    q = args.dividend_yield if args.dividend_yield is not None else get_dividend_yield(args.ticker)
    cc_pnl, cc_log, _ = __import__("covered_call_report").run_backtest(
        prices, args.cycle_days, args.otm_pct, args.risk_free_rate, q,
        shares=args.shares, iv_lookback=args.iv_lookback,
    )
    put_pnl, put_log = run_short_put(
        prices, args.cycle_days, args.otm_pct, args.risk_free_rate, q,
        shares=args.shares, iv_lookback=args.iv_lookback,
    )

    print_comparison(args.ticker, prices, args.cycle_days, args.otm_pct, args.shares,
                     cc_pnl, put_pnl, q, args.risk_free_rate)
    if args.put_csv_out:
        put_log.to_csv(args.put_csv_out, index=False)
        print(f"\nShort-put cycle log saved to {args.put_csv_out}")


if __name__ == "__main__":
    main()
