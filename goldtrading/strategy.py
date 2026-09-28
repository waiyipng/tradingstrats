"""Pure decision rules for the gold cash-and-carry and calendar-spread strategies."""
from __future__ import annotations

from goldtrading.carry import basis as compute_basis, theoretical_calendar_spread, theoretical_futures_price
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
        )

    if open_positions >= config.max_concurrent_positions:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=None, theoretical_futures_price=None, net_edge_after_costs=None,
            reasons=["max concurrent gold positions already open"],
        )

    fair_price = theoretical_futures_price(spot_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, near.days_to_expiry)
    raw_basis = compute_basis(near.mid_price, fair_price)
    net_edge = _net_edge(raw_basis, spot_price, config)

    if raw_basis <= 0:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["futures trade at or below carry-cost fair value; reverse cash-and-carry (short spot) is not supported"],
        )

    if net_edge / spot_price < config.min_net_edge_pct:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["net edge after estimated round-trip costs is below the minimum required edge"],
        )

    contracts = _max_hedged_contracts(spot_price, account, config)
    if contracts <= 0:
        return CarryRecommendation(
            action="HOLD", contracts=0, spot_quantity_oz=0.0, spot=snapshot.spot, near_future=near,
            entry_basis=raw_basis, theoretical_futures_price=fair_price, net_edge_after_costs=net_edge,
            reasons=["insufficient cash or notional headroom for a fully hedged lot"],
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
    )


def evaluate_calendar_spread(config: GoldConfig, account: AccountState, snapshot: MarketSnapshot, open_positions: int) -> CalendarRecommendation:
    spot_price = snapshot.spot.mid_price
    near, far = snapshot.near_future, snapshot.far_future
    if spot_price is None or near is None or far is None or near.mid_price is None or far.mid_price is None:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=None, theoretical_spread=None, mispricing=None, net_edge_after_costs=None,
            reasons=["missing spot or futures quotes for both contract months"],
        )

    if open_positions >= config.max_concurrent_positions:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=None, theoretical_spread=None, mispricing=None, net_edge_after_costs=None,
            reasons=["max concurrent gold positions already open"],
        )

    fair_spread = theoretical_calendar_spread(spot_price, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, near.days_to_expiry, far.days_to_expiry)
    market_spread = far.mid_price - near.mid_price
    mispricing = market_spread - fair_spread
    net_edge = _net_edge(mispricing, spot_price, config)

    if net_edge / spot_price < config.min_net_edge_pct:
        return CalendarRecommendation(
            action="HOLD", contracts=0, near_future=near, far_future=far,
            market_spread=market_spread, theoretical_spread=fair_spread, mispricing=mispricing, net_edge_after_costs=net_edge,
            reasons=["calendar mispricing net of estimated round-trip costs is below the minimum required edge"],
        )

    action = "SELL_CALENDAR_SPREAD" if mispricing > 0 else "BUY_CALENDAR_SPREAD"
    reason = "market spread is wider than carry-cost fair value" if mispricing > 0 else "market spread is narrower than carry-cost fair value"
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
    )
