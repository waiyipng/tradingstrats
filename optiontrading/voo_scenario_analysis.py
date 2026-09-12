"""Scenario analysis for monthly VOO covered calls and cash-settled puts."""

import argparse
from datetime import datetime

import numpy as np
from scipy.stats import norm

from covered_call_report import get_dividend_yield, get_price_history


MONTHS = 36
SHARES = 100
OTM_PCT = 5.0
RISK_FREE_RATE = 0.04
VOLATILITY = 0.20
MONTHS_PER_YEAR = 12


def bs_call_price(spot, strike, years, rate, dividend_yield, volatility):
    d1 = (np.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility**2) * years) / (
        volatility * np.sqrt(years)
    )
    d2 = d1 - volatility * np.sqrt(years)
    return spot * np.exp(-dividend_yield * years) * norm.cdf(d1) - strike * np.exp(
        -rate * years
    ) * norm.cdf(d2)


def bs_put_price(spot, strike, years, rate, dividend_yield, volatility):
    d1 = (np.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility**2) * years) / (
        volatility * np.sqrt(years)
    )
    d2 = d1 - volatility * np.sqrt(years)
    return strike * np.exp(-rate * years) * norm.cdf(-d2) - spot * np.exp(
        -dividend_yield * years
    ) * norm.cdf(-d1)


def run_scenario(start_price, monthly_change, dividend_yield):
    monthly_years = 1 / MONTHS_PER_YEAR
    path = [start_price * (1 + monthly_change) ** month for month in range(MONTHS + 1)]

    covered_call_cash = -start_price * SHARES
    put_cash = start_price * SHARES
    call_assignments = 0
    put_intrinsic_loss = 0.0
    call_premiums = 0.0
    put_premiums = 0.0
    shares_held = True

    for month in range(MONTHS):
        spot = path[month]
        next_spot = path[month + 1]
        call_strike = spot * (1 + OTM_PCT / 100)
        put_strike = spot * (1 - OTM_PCT / 100)
        call_premium = bs_call_price(
            spot, call_strike, monthly_years, RISK_FREE_RATE, dividend_yield, VOLATILITY
        ) * SHARES
        put_premium = bs_put_price(
            spot, put_strike, monthly_years, RISK_FREE_RATE, dividend_yield, VOLATILITY
        ) * SHARES
        covered_call_cash += call_premium
        put_cash += put_premium
        call_premiums += call_premium
        put_premiums += put_premium

        if next_spot >= call_strike:
            covered_call_cash += call_strike * SHARES
            shares_held = False
            call_assignments += 1
        else:
            shares_held = True

        put_loss = max(put_strike - next_spot, 0.0) * SHARES
        put_cash -= put_loss
        put_intrinsic_loss += put_loss

        if not shares_held and month < MONTHS - 1:
            covered_call_cash -= next_spot * SHARES
            shares_held = True

    covered_call_value = covered_call_cash + (path[-1] * SHARES if shares_held else 0.0)
    covered_call_pnl = covered_call_value
    put_pnl = put_cash - start_price * SHARES
    hold_pnl = (path[-1] - start_price) * SHARES

    return {
        "final_price": path[-1],
        "covered_call_pnl": covered_call_pnl,
        "put_pnl": put_pnl,
        "combined_pnl": covered_call_pnl + put_pnl,
        "hold_pnl": hold_pnl,
        "call_premiums": call_premiums,
        "put_premiums": put_premiums,
        "put_intrinsic_loss": put_intrinsic_loss,
        "call_assignments": call_assignments,
    }


def main():
    parser = argparse.ArgumentParser(description="Run deterministic VOO option scenarios.")
    parser.add_argument("--start-price", type=float, default=None)
    parser.add_argument("--dividend-yield", type=float, default=None)
    args = parser.parse_args()

    if args.start_price is None:
        end = datetime.today().strftime("%Y-%m-%d")
        prices = get_price_history("VOO", "2020-01-01", end)
        start_price = float(prices.iloc[-1])
    else:
        start_price = args.start_price

    if start_price <= 0:
        parser.error("--start-price must be greater than zero")

    dividend_yield = args.dividend_yield
    if dividend_yield is None:
        dividend_yield = get_dividend_yield("VOO")

    scenarios = (
        ("VOO +2% monthly", 0.02),
        ("VOO flat", 0.00),
        ("VOO -2% monthly", -0.02),
    )
    print(f"Starting VOO price: ${start_price:,.2f}")
    print(f"Dividend yield: {dividend_yield:.2%}; option volatility: {VOLATILITY:.0%}")
    print(f"Monthly options: {OTM_PCT:.0f}% OTM, {MONTHS} cycles, {SHARES} shares")
    print("\n" + "=" * 112)
    print(f"{'Scenario':<20}{'Final VOO':>13}{'CC P&L':>14}{'CC vs hold':>14}{'Put P&L':>14}{'Put vs hold':>14}{'Combined':>15}{'Comb. vs 100sh':>17}")
    print("-" * 112)

    for name, monthly_change in scenarios:
        result = run_scenario(start_price, monthly_change, dividend_yield)
        print(
            f"{name:<20}${result['final_price']:>11,.2f}"
            f"${result['covered_call_pnl']:>12,.2f}"
            f"${result['covered_call_pnl'] - result['hold_pnl']:>12,.2f}"
            f"${result['put_pnl']:>12,.2f}"
            f"${result['put_pnl'] - result['hold_pnl']:>12,.2f}"
            f"${result['combined_pnl']:>13,.2f}"
            f"${result['combined_pnl'] - result['hold_pnl']:>15,.2f}"
        )
        print(
            f"  premiums: call ${result['call_premiums']:,.2f}, put ${result['put_premiums']:,.2f}; "
            f"put cash losses ${result['put_intrinsic_loss']:,.2f}; "
            f"call assignments {result['call_assignments']}"
        )

    print("=" * 112)
    print("CC and put each use 100 shares/notional; combined is the sum of both separate allocations.")
    print("Combined vs 100sh compares that total with simply holding 100 VOO shares.")
    print("Puts are cash-settled; no shares are purchased. No fees, slippage, or dividends received by the holder are included.")


if __name__ == "__main__":
    main()
