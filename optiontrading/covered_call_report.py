"""
Covered Call Backtester - Readable Report Edition
===================================================
Backtests "sell an N%-OTM call every M days" against buy-and-hold, using
REAL historical daily prices via yfinance, and produces:
  1. A clean, plain-English summary printed to the terminal
  2. A chart (PNG) comparing the covered-call equity curve vs buy-and-hold
  3. A CSV log of every cycle (strike, premium, called away or not)

Defaults to VOO over the last 3 years, monthly (30-day) cycles, 5% OTM -
just run it with no arguments to get that.

Premiums are priced with Black-Scholes using trailing REALIZED volatility as
an implied-vol proxy (see the long comment in covered_call_backtest.py for
why, and its limitations - real quoted premiums typically run a bit higher).

Usage
-----
    pip install yfinance numpy pandas scipy matplotlib --break-system-packages

    python covered_call_report.py
    python covered_call_report.py --ticker GOOGL --cycle-days 45
    python covered_call_report.py --ticker VOO --start 2023-09-08 --end 2026-09-08
"""

import argparse
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def get_price_history(ticker: str, start: str, end: str) -> pd.Series:
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance is not installed. Run:\n  pip install yfinance --break-system-packages")
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        sys.exit(f"No data returned for {ticker} between {start} and {end}. Check the ticker/date range.")

    # Recent yfinance versions can return a single-ticker frame with a MultiIndex
    # column layout (e.g. ('Close', 'VOO')), which needs to be normalized to a
    # single price series before downstream scalar indexing works.
    if isinstance(df.columns, pd.MultiIndex):
        close = df.xs("Close", axis=1, level=0, drop_level=True)
    else:
        close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]

    if isinstance(close, pd.DataFrame):
        close = close.squeeze("columns")

    return pd.to_numeric(close, errors="coerce").dropna()


def get_dividend_yield(ticker: str) -> float:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        y = info.get("dividendYield") or 0.0
        return y / 100 if y > 1 else y
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

def get_iv_estimate(prices: pd.Series, as_of_idx: int, lookback: int = 30) -> float:
    window = prices.iloc[max(0, as_of_idx - lookback):as_of_idx + 1]
    if len(window) < 5:
        return 0.20
    log_ret = np.log(window / window.shift(1)).dropna()
    return float(log_ret.std() * np.sqrt(252))


def bs_call_price(S, K, T, r, q, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(prices: pd.Series, cycle_days: int, otm_pct: float,
                  r: float, q: float, shares: int = 100, iv_lookback: int = 30):
    """
    Returns:
      final_value: covered-call strategy's net P&L at the end (cash nets out
                   the initial share purchase, so this IS the P&L, not raw equity)
      log_df:      one row per option cycle (strike, premium, outcome)
      pnl_points:  list of (date, covered_call_pnl_so_far) at each cycle boundary,
                   used to draw the equity-curve chart as a step series
    """
    dates = prices.index
    n = len(prices)
    idx = 0
    holding = True
    cash = -shares * float(prices.iloc[0])
    log = []
    pnl_points = [(dates[0], 0.0)]  # P&L starts at zero on day 1

    while idx < n - 1:
        S0 = float(prices.iloc[idx])
        if not holding:
            cash -= shares * S0
            holding = True

        K = S0 * (1 + otm_pct / 100)
        sigma = get_iv_estimate(prices, idx, lookback=iv_lookback)
        T = cycle_days / 365
        premium = bs_call_price(S0, K, T, r, q, sigma) * shares
        cash += premium

        target_date = dates[idx] + timedelta(days=cycle_days)
        next_idx = prices.index.searchsorted(target_date)
        next_idx = min(next_idx, n - 1)
        if next_idx <= idx:
            next_idx = idx + 1

        S1 = float(prices.iloc[next_idx])
        called_away = S1 >= K
        if called_away:
            cash += K * shares
            holding = False

        log.append({
            "cycle_start": dates[idx].date(), "spot_start": round(S0, 2),
            "strike": round(K, 2), "iv_used_pct": round(sigma * 100, 1),
            "premium_collected": round(premium, 2), "cycle_end": dates[next_idx].date(),
            "spot_end": round(S1, 2), "called_away": called_away,
        })

        cc_pnl_so_far = cash + (shares * S1 if holding else 0)
        pnl_points.append((dates[next_idx], cc_pnl_so_far))
        idx = next_idx

    final_value = pnl_points[-1][1]
    return final_value, pd.DataFrame(log), pnl_points


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(ticker, cycle_days, otm_pct, prices, final_value, log_df, initial_outlay, q, r):
    n_cycles = len(log_df)
    n_capped = int(log_df["called_away"].sum()) if n_cycles else 0
    buy_hold = prices.iloc[-1] * (initial_outlay / prices.iloc[0]) - initial_outlay
    total_premium = log_df["premium_collected"].sum() if n_cycles else 0.0

    cc_return_pct = final_value / initial_outlay * 100
    bh_return_pct = buy_hold / initial_outlay * 100

    bar = "=" * 58
    print(bar)
    print(f"  COVERED CALL BACKTEST REPORT — {ticker}")
    print(bar)
    print(f"  Period:            {prices.index[0].date()} to {prices.index[-1].date()}")
    print(f"  Strategy:          Sell {otm_pct:.0f}%-OTM call every {cycle_days} days")
    print(f"  Contract size:     100 shares")
    print(f"  Start price:       ${prices.iloc[0]:.2f}")
    print(f"  End price:         ${prices.iloc[-1]:.2f}")
    print(f"  Initial outlay:    ${initial_outlay:,.2f}")
    print("-" * 58)
    print(f"  Cycles completed:      {n_cycles}")
    print(f"  Times called away:     {n_capped}  ({n_capped/n_cycles*100 if n_cycles else 0:.0f}% of cycles)")
    print(f"  Total premium collected: ${total_premium:,.2f}")
    print("-" * 58)
    print(f"  {'Strategy':<22}{'P&L':>15}{'Return':>15}")
    print(f"  {'Covered call':<22}{'$'+format(final_value, ',.0f'):>15}{cc_return_pct:>14.1f}%")
    print(f"  {'Buy & hold':<22}{'$'+format(buy_hold, ',.0f'):>15}{bh_return_pct:>14.1f}%")
    print("-" * 58)
    winner = "Covered call" if final_value > buy_hold else "Buy & hold"
    diff = abs(final_value - buy_hold)
    print(f"  Result: {winner} came out ahead by ${diff:,.0f} over this period.")
    print(bar)
    print("  Notes:")
    print(f"   - Dividend yield used in option pricing: {q:.2%}/yr (excluded from buy&hold cash P&L above)")
    print(f"   - Risk-free rate used: {r:.2%}")
    print("   - Premiums are Black-Scholes estimates using realized vol as an IV proxy,")
    print("     not actual quoted market prices. See script header for details.")
    print(bar)


def make_chart(prices, pnl_points, ticker, cycle_days, otm_pct, shares, out_path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skipping chart. Run: pip install matplotlib --break-system-packages")
        return None

    cc_dates = [p[0] for p in pnl_points]
    cc_pnl = [p[1] for p in pnl_points]

    initial_price = float(prices.iloc[0])
    bh_pnl = shares * (prices - initial_price)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(prices.index, bh_pnl, label="Buy & hold P&L", linewidth=2)
    ax.step(cc_dates, cc_pnl, where="post",
            label=f"Covered call P&L ({cycle_days}d, {otm_pct:.0f}% OTM)", linewidth=2)
    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_title(f"{ticker}: Covered Call vs Buy & Hold — Cumulative P&L")
    ax.set_ylabel("P&L ($)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nChart saved to {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Covered call backtester with readable report + chart")
    p.add_argument("--ticker", default="VOO")
    p.add_argument("--start", default=(datetime.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d"))
    p.add_argument("--end", default=datetime.today().strftime("%Y-%m-%d"))
    p.add_argument("--otm-pct", type=float, default=5.0)
    p.add_argument("--cycle-days", type=int, default=30)
    p.add_argument("--shares", type=int, default=100)
    p.add_argument("--risk-free-rate", type=float, default=0.04)
    p.add_argument("--dividend-yield", type=float, default=None)
    p.add_argument("--iv-lookback", type=int, default=30)
    p.add_argument("--csv-out", default="covered_call_cycles.csv")
    p.add_argument("--chart-out", default="covered_call_chart.png")
    args = p.parse_args()

    print(f"Fetching {args.ticker} prices from {args.start} to {args.end}...\n")
    prices = get_price_history(args.ticker, args.start, args.end)
    q = args.dividend_yield if args.dividend_yield is not None else get_dividend_yield(args.ticker)

    final_value, log_df, pnl_points = run_backtest(
        prices, args.cycle_days, args.otm_pct, args.risk_free_rate, q,
        shares=args.shares, iv_lookback=args.iv_lookback,
    )
    initial_outlay = args.shares * float(prices.iloc[0])

    print_report(args.ticker, args.cycle_days, args.otm_pct, prices, final_value,
                 log_df, initial_outlay, q, args.risk_free_rate)

    if args.csv_out:
        log_df.to_csv(args.csv_out, index=False)
        print(f"\nFull cycle-by-cycle log saved to {args.csv_out}")

    if args.chart_out:
        make_chart(prices, pnl_points, args.ticker, args.cycle_days, args.otm_pct,
                   args.shares, args.chart_out)


if __name__ == "__main__":
    main()