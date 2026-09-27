"""Historical, modeled-premium VOO wheel backtest versus HKD cash."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import yfinance as yf
from scipy.stats import norm

from covered_call_report import get_dividend_yield, get_iv_estimate


def prices(ticker: str, start: str, end: str):
    frame = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    close = frame["Close"]
    if hasattr(close, "columns"):
        close = close.squeeze("columns")
    return close.dropna()


def option_price(spot, strike, years, rate, dividend, volatility, right):
    if years <= 0 or volatility <= 0:
        return max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)
    d1 = (np.log(spot / strike) + (rate - dividend + 0.5 * volatility**2) * years) / (volatility * np.sqrt(years))
    d2 = d1 - volatility * np.sqrt(years)
    if right == "C":
        return spot * np.exp(-dividend * years) * norm.cdf(d1) - strike * np.exp(-rate * years) * norm.cdf(d2)
    return strike * np.exp(-rate * years) * norm.cdf(-d2) - spot * np.exp(-dividend * years) * norm.cdf(-d1)


def run(start="2023-09-20", end="2026-09-21", initial_hkd=1_000_000.0, cash_rate=0.01):
    cycle_days = 30
    otm_pct = 5.0
    contract_size = 100
    risk_free = 0.04
    voo = prices("VOO", start, end)
    fx = prices("HKD=X", start, end)
    fx_start = float(fx.loc[fx.index >= voo.index[0]].iloc[0])
    fx_end = float(fx.iloc[-1])
    starting_usd = initial_hkd / fx_start
    dividend_yield = get_dividend_yield("VOO")
    cash = starting_usd
    shares = 0
    index = 0
    puts = calls = put_assignments = call_assignments = 0
    premiums = 0.0
    while index < len(voo) - 1:
        spot = float(voo.iloc[index])
        target = voo.index[index] + timedelta(days=cycle_days)
        end_index = min(voo.index.searchsorted(target), len(voo) - 1)
        end_index = max(end_index, index + 1)
        end_spot = float(voo.iloc[end_index])
        volatility = max(0.05, get_iv_estimate(voo, index, lookback=30))
        years = cycle_days / 365
        if shares == 0:
            strike = math.floor(spot * (1 - otm_pct / 100))
            contracts = math.floor(cash / (strike * contract_size))
            if contracts == 0:
                break
            premium = option_price(spot, strike, years, risk_free, dividend_yield, volatility, "P") * contract_size * contracts
            cash += premium
            premiums += premium
            puts += 1
            if end_spot < strike:
                cash -= strike * contract_size * contracts
                shares = contract_size * contracts
                put_assignments += contracts
        else:
            strike = math.ceil(spot * (1 + otm_pct / 100))
            contracts = shares // contract_size
            premium = option_price(spot, strike, years, risk_free, dividend_yield, volatility, "C") * contract_size * contracts
            cash += premium
            premiums += premium
            calls += 1
            if end_spot >= strike:
                cash += strike * contract_size * contracts
                shares -= contract_size * contracts
                call_assignments += contracts
        index = end_index

    final_usd = cash + shares * float(voo.iloc[-1])
    final_hkd = final_usd * fx_end
    cash_hkd = initial_hkd * (1 + cash_rate) ** 3
    buy_hold_hkd = starting_usd / float(voo.iloc[0]) * float(voo.iloc[-1]) * fx_end
    return {
        "period": f"{voo.index[0].date()} to {voo.index[-1].date()}",
        "fx_start": fx_start,
        "fx_end": fx_end,
        "starting_usd": starting_usd,
        "dividend_yield": dividend_yield,
        "wheel_final_hkd": final_hkd,
        "wheel_profit_hkd": final_hkd - initial_hkd,
        "wheel_return": final_hkd / initial_hkd - 1,
        "cash_final_hkd": cash_hkd,
        "cash_profit_hkd": cash_hkd - initial_hkd,
        "cash_return": cash_hkd / initial_hkd - 1,
        "wheel_minus_cash_hkd": final_hkd - cash_hkd,
        "buy_hold_final_hkd": buy_hold_hkd,
        "buy_hold_profit_hkd": buy_hold_hkd - initial_hkd,
        "buy_hold_return": buy_hold_hkd / initial_hkd - 1,
        "put_cycles": puts,
        "call_cycles": calls,
        "put_assignments": put_assignments,
        "call_assignments": call_assignments,
        "premiums_usd": premiums,
        "ending_shares": shares,
        "ending_cash_usd": cash,
    }


if __name__ == "__main__":
    result = run()
    print(f"period={result['period']}")
    print(f"fx_start={result['fx_start']:.6f}; fx_end={result['fx_end']:.6f}; starting_usd={result['starting_usd']:,.2f}")
    print(f"wheel_final_hkd={result['wheel_final_hkd']:,.2f}; wheel_profit_hkd={result['wheel_profit_hkd']:,.2f}; wheel_return={result['wheel_return']:.2%}")
    print(f"cash_final_hkd={result['cash_final_hkd']:,.2f}; cash_profit_hkd={result['cash_profit_hkd']:,.2f}; cash_return={result['cash_return']:.2%}")
    print(f"wheel_minus_cash_hkd={result['wheel_minus_cash_hkd']:,.2f}")
    print(f"buy_hold_final_hkd={result['buy_hold_final_hkd']:,.2f}; buy_hold_profit_hkd={result['buy_hold_profit_hkd']:,.2f}; buy_hold_return={result['buy_hold_return']:.2%}")
    print(f"put_cycles={result['put_cycles']}; call_cycles={result['call_cycles']}; put_assignments={result['put_assignments']}; call_assignments={result['call_assignments']}")
    print(f"premiums_usd={result['premiums_usd']:,.2f}; ending_shares={result['ending_shares']}; ending_cash_usd={result['ending_cash_usd']:,.2f}")