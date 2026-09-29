"""Pure decision rules for the gold cash-and-carry and calendar-spread strategies."""
from __future__ import annotations

from goldtrading.carry import basis as compute_basis, build_ladder, theoretical_calendar_spread, theoretical_futures_price
from goldtrading.config import GoldConfig
from goldtrading.models import AccountState, CalendarRecommendation, CarryRecommendation, MarketSnapshot


def _net_edge(mispricing: float, spot_price: float, config: GoldConfig) -> float:
    estimated_round_trip_cost = spot_price * config.round_trip_cost_pct
    return abs(mispricing) - estimated_round_trip_cost


def _max_hedged_contracts(spot_price: float, account: AccountState, config: GoldConfig) -> int:
    notional_per_contract = spot_price * config.futures_multiplier_oz
    if notional_per_contract <= 0:
        return 0
    notional_affordable = int((account.net_liquidation * config.max_notional_pct_of_net_liq) // notional_per_contract)
    cash_affordable = int(account.cash // notional_per_contract)
    return max(0, min(notional_affordable, cash_affordable))


def evaluate_cash_and_carry(config: GoldConfig, account: AccountState, snapshot: MarketSnapshot, open_positions: int) -> CarryRecommendation:
    spot_price = snapshot.spot.mid_price
    near = snapshot.near_future
    if spot_price is None or near is None or near.mid_price is None:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=None, theoretical_futures_price=None, net_edge_after_costs=None,
            reasons=["missing spot or near-month futures quote"],
            verdict="Cannot evaluate: missing a live spot or near-month futures quote.",
        )

    if open_positions >= config.max_concurrent_positions:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=None, theoretical_futures_price=None, net_edge_after_costs=None,
            reasons=["max concurrent gold positions already open"],
            verdict=f"Not evaluated: {open_positions} of {config.max_concurrent_positions} max concurrent gold position(s) already open.",
        )

    ladder = build_ladder(spot_price, near.mid_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, near.days_to_expiry)
    fair_price = ladder.theoretical_price
    raw_basis = ladder.raw_mispricing
    round_trip_cost = round(spot_price * config.round_trip_cost_pct, 4)
    min_net_edge_threshold = round(spot_price * config.min_net_edge_pct, 4)
    net_edge = _net_edge(raw_basis, spot_price, config)

    if raw_basis <= 0:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["futures trade at or below carry-cost fair value; reverse cash-and-carry (short spot) is not supported"],
            ladder=ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
            is_arbitrage_opportunity=False,
            verdict=(
                f"No arbitrage: near-month futures (${near.mid_price:,.2f}) trade at or below the carry-cost fair value "
                f"(${fair_price:,.2f}), a raw basis of ${raw_basis:,.4f}. The only mispricing direction available here would be "
                "reverse cash-and-carry (short spot, long futures), which this strategy never attempts because shorting "
                "physical/unallocated gold is impractical for a retail account."
            ),
        )

    if net_edge / spot_price < config.min_net_edge_pct:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["net edge after estimated round-trip costs is below the minimum required edge"],
            ladder=ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
            is_arbitrage_opportunity=False,
            verdict=(
                f"No arbitrage: raw basis of ${raw_basis:,.4f} nets to ${net_edge:,.4f} after an estimated ${round_trip_cost:,.4f} "
                f"round-trip cost ({config.round_trip_cost_pct:.3%} of spot notional). That net edge is below the required "
                f"minimum of ${min_net_edge_threshold:,.4f} ({config.min_net_edge_pct:.3%} of spot notional) — the raw "
                "mispricing exists but is too small to clear real-world transaction costs, so it is not a tradable arbitrage."
            ),
        )

    contracts = _max_hedged_contracts(spot_price, account, config)
    if contracts <= 0:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["insufficient cash or notional headroom for a fully hedged lot"],
            ladder=ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
            is_arbitrage_opportunity=True,
            verdict=(
                f"Arbitrage exists but is not actionable: net edge of ${net_edge:,.4f} clears the ${min_net_edge_threshold:,.4f} "
                "minimum threshold, but there is insufficient cash or notional headroom to size even one fully-hedged "
                f"({config.futures_multiplier_oz} oz spot vs. 1 MGC contract) lot within the {config.max_notional_pct_of_net_liq:.0%} "
                "of net liquidation cap."
            ),
        )

    return CarryRecommendation(
        action="CASH_AND_CARRY",
        contracts=contracts,
        spot_quantity_oz=float(contracts * config.futures_multiplier_oz),
        spot=snapshot.spot,
        near_future=near,
        entry_basis=raw_basis,
        theoretical_futures_price=fair_price,
        net_edge_after_costs=net_edge,
        reasons=["market futures price exceeds carry-cost fair value by more than the minimum net edge"],
        ladder=ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
        is_arbitrage_opportunity=True,
        verdict=(
            f"Arbitrage confirmed: near-month futures trade ${raw_basis:,.4f} above the carry-cost fair value of "
            f"${fair_price:,.2f}. Net of an estimated ${round_trip_cost:,.4f} round-trip cost, the ${net_edge:,.4f} edge "
            f"clears the ${min_net_edge_threshold:,.4f} minimum threshold — entering {contracts} contract(s) of "
            "cash-and-carry (long spot, short futures)."
        ),
    )


def evaluate_calendar_spread(config: GoldConfig, account: AccountState, snapshot: MarketSnapshot, open_positions: int) -> CalendarRecommendation:
    spot_price = snapshot.spot.mid_price
    near, far = snapshot.near_future, snapshot.far_future
    if spot_price is None or near is None or far is None or near.mid_price is None or far.mid_price is None:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=None, theoretical_spread=None, mispricing=None, net_edge_after_costs=None,
            reasons=["missing spot or futures quotes for both contract months"],
            verdict="Cannot evaluate: missing a live spot or futures quote for one or both contract months.",
        )

    if open_positions >= config.max_concurrent_positions:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=None, theoretical_spread=None, mispricing=None, net_edge_after_costs=None,
            reasons=["max concurrent gold positions already open"],
            verdict=f"Not evaluated: {open_positions} of {config.max_concurrent_positions} max concurrent gold position(s) already open.",
        )

    near_ladder = build_ladder(spot_price, near.mid_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, near.days_to_expiry)
    far_ladder = build_ladder(spot_price, far.mid_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, far.days_to_expiry)
    fair_spread = far_ladder.theoretical_price - near_ladder.theoretical_price
    market_spread = far.mid_price - near.mid_price
    mispricing = market_spread - fair_spread
    round_trip_cost = round(spot_price * config.round_trip_cost_pct, 4)
    min_net_edge_threshold = round(spot_price * config.min_net_edge_pct, 4)
    net_edge = _net_edge(mispricing, spot_price, config)

    if net_edge / spot_price < config.min_net_edge_pct:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=market_spread, theoretical_spread=fair_spread, mispricing=mispricing, net_edge_after_costs=net_edge,
            reasons=["calendar mispricing net of estimated round-trip costs is below the minimum required edge"],
            near_ladder=near_ladder, far_ladder=far_ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
            is_arbitrage_opportunity=False,
            verdict=(
                f"No arbitrage: market spread (far ${far.mid_price:,.2f} - near ${near.mid_price:,.2f} = ${market_spread:,.4f}) "
                f"vs. carry-cost fair spread of ${fair_spread:,.4f} gives a raw mispricing of ${mispricing:,.4f}. Net of an "
                f"estimated ${round_trip_cost:,.4f} round-trip cost, the ${net_edge:,.4f} edge is below the required minimum "
                f"of ${min_net_edge_threshold:,.4f} ({config.min_net_edge_pct:.3%} of spot notional) — not a tradable arbitrage."
            ),
        )

    action = "SELL_CALENDAR_SPREAD" if mispricing > 0 else "BUY_CALENDAR_SPREAD"
    reason = "market spread is wider than carry-cost fair value" if mispricing > 0 else "market spread is narrower than carry-cost fair value"
    direction = (
        "market spread is too wide relative to fair value, so sell the spread (short far month, long near month)"
        if mispricing > 0
        else "market spread is too narrow relative to fair value, so buy the spread (long far month, short near month)"
    )
    return CalendarRecommendation(
        action=action,
        contracts=config.calendar_contracts_per_trade,
        near_future=near,
        far_future=far,
        market_spread=market_spread,
        theoretical_spread=fair_spread,
        mispricing=mispricing,
        net_edge_after_costs=net_edge,
        reasons=[reason],
        near_ladder=near_ladder, far_ladder=far_ladder, round_trip_cost=round_trip_cost, min_net_edge_threshold=min_net_edge_threshold,
        is_arbitrage_opportunity=True,
        verdict=(
            f"Arbitrage confirmed: raw mispricing of ${mispricing:,.4f} (market spread ${market_spread:,.4f} vs. fair spread "
            f"${fair_spread:,.4f}) nets to ${net_edge:,.4f} after an estimated ${round_trip_cost:,.4f} round-trip cost, "
            f"clearing the ${min_net_edge_threshold:,.4f} minimum threshold. The {direction}."
        ),
    )
