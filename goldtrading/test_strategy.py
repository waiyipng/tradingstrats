import unittest

from goldtrading.carry import theoretical_calendar_spread, theoretical_futures_price
from goldtrading.config import GoldConfig
from goldtrading.models import AccountState, FuturesQuote, MarketSnapshot, SpotQuote
from goldtrading.strategy import evaluate_calendar_spread, evaluate_cash_and_carry


def _snapshot(spot_mid, near_mid, near_days, far_mid=None, far_days=None):
    spot = SpotQuote(symbol="XAUUSD", bid=spot_mid - 0.5, ask=spot_mid + 0.5)
    near = FuturesQuote(symbol="MGC", local_symbol="MGCZ26", expiry="20261228", bid=near_mid - 0.1, ask=near_mid + 0.1, days_to_expiry=near_days, min_tick=0.10)
    far = None
    if far_mid is not None:
        far = FuturesQuote(symbol="MGC", local_symbol="MGCG27", expiry="20270228", bid=far_mid - 0.1, ask=far_mid + 0.1, days_to_expiry=far_days, min_tick=0.10)
    return MarketSnapshot(spot=spot, near_future=near, far_future=far)


class CashAndCarryStrategyTests(unittest.TestCase):
    def setUp(self):
        self.config = GoldConfig()
        self.account = AccountState(cash=50_000.0, net_liquidation=100_000.0)

    def test_holds_when_futures_price_is_close_to_fair_value(self):
        fair = theoretical_futures_price(2000.0, self.config.financing_rate_annual, self.config.storage_rate_annual, self.config.convenience_yield_annual, 90)
        snapshot = _snapshot(spot_mid=2000.0, near_mid=fair + 0.5, near_days=90)
        recommendation = evaluate_cash_and_carry(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "HOLD")

    def test_trades_when_futures_are_rich_enough_to_clear_costs(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2050.0, near_days=90)
        recommendation = evaluate_cash_and_carry(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "CASH_AND_CARRY")
        self.assertGreater(recommendation.contracts, 0)
        self.assertEqual(recommendation.spot_quantity_oz, recommendation.contracts * self.config.futures_multiplier_oz)

    def test_holds_reverse_carry_opportunity(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=1950.0, near_days=90)
        recommendation = evaluate_cash_and_carry(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "HOLD")
        self.assertIn("reverse cash-and-carry", recommendation.reasons[0])

    def test_holds_when_max_concurrent_positions_reached(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2050.0, near_days=90)
        recommendation = evaluate_cash_and_carry(self.config, self.account, snapshot, open_positions=self.config.max_concurrent_positions)
        self.assertEqual(recommendation.action, "HOLD")

    def test_holds_when_account_cannot_afford_a_hedged_lot(self):
        poor_account = AccountState(cash=100.0, net_liquidation=100.0)
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2050.0, near_days=90)
        recommendation = evaluate_cash_and_carry(self.config, poor_account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "HOLD")


class CalendarSpreadStrategyTests(unittest.TestCase):
    def setUp(self):
        self.config = GoldConfig()
        self.account = AccountState(cash=50_000.0, net_liquidation=100_000.0)

    def test_sells_spread_when_market_spread_is_too_wide(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2010.0, near_days=30, far_mid=2060.0, far_days=120)
        recommendation = evaluate_calendar_spread(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "SELL_CALENDAR_SPREAD")

    def test_buys_spread_when_market_spread_is_too_narrow(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2010.0, near_days=30, far_mid=2015.0, far_days=120)
        recommendation = evaluate_calendar_spread(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "BUY_CALENDAR_SPREAD")

    def test_holds_when_spread_matches_fair_value(self):
        config = self.config
        fair_spread = theoretical_calendar_spread(2000.0, config.financing_rate_annual, config.storage_rate_annual, config.convenience_yield_annual, 30, 120)
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2010.0, near_days=30, far_mid=2010.0 + fair_spread, far_days=120)
        recommendation = evaluate_calendar_spread(config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "HOLD")

    def test_holds_without_a_far_month_quote(self):
        snapshot = _snapshot(spot_mid=2000.0, near_mid=2010.0, near_days=30)
        recommendation = evaluate_calendar_spread(self.config, self.account, snapshot, open_positions=0)
        self.assertEqual(recommendation.action, "HOLD")


if __name__ == "__main__":
    unittest.main()
