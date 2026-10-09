import unittest
from datetime import datetime, timedelta

from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.models import AccountState, CallLeg
from bullcallspread.strategy import build_exit_plan, evaluate_bull_call_spread, select_spread


def _leg(strike, bid, ask):
    return CallLeg(symbol="MS", expiry="20270115", strike=strike, bid=bid, ask=ask, delta=None)


class SelectSpreadTests(unittest.TestCase):
    def setUp(self):
        self.config = BullCallSpreadConfig()
        self.spot = 100.0
        self.legs = [
            _leg(95.0, 7.0, 7.2),
            _leg(100.0, 4.0, 4.2),
            _leg(105.0, 2.0, 2.2),
            _leg(110.0, 0.8, 1.0),
        ]

    def test_picks_long_at_or_below_spot_and_short_near_target(self):
        selection = select_spread(self.config, self.spot, target_price=108.0, legs=self.legs)
        self.assertIsNotNone(selection)
        long_leg, short_leg = selection
        self.assertEqual(long_leg.strike, 100.0)
        self.assertGreaterEqual(short_leg.strike, 100.0)

    def test_returns_none_when_no_strikes_available(self):
        self.assertIsNone(select_spread(self.config, self.spot, target_price=108.0, legs=[]))


class EvaluateBullCallSpreadTests(unittest.TestCase):
    def setUp(self):
        self.config = BullCallSpreadConfig()
        self.account = AccountState(cash=50_000.0, net_liquidation=100_000.0, excess_liquidity=80_000.0)
        self.legs = [
            _leg(95.0, 7.0, 7.2),
            _leg(100.0, 4.0, 4.2),
            _leg(105.0, 2.0, 2.2),
            _leg(110.0, 0.8, 1.0),
        ]

    def test_recommends_spread_with_positive_max_profit(self):
        recommendation = evaluate_bull_call_spread(
            self.config, self.account, spot=100.0, expiry="20270115", legs=self.legs,
            target_price=108.0, target_date="2027-01-01", amount=1000.0,
        )
        self.assertEqual(recommendation.action, "BUY_BULL_CALL_SPREAD")
        self.assertGreater(recommendation.contracts, 0)
        self.assertGreater(recommendation.max_profit, 0)
        self.assertLess(recommendation.max_loss, 0.01 + recommendation.net_debit * 100 * recommendation.contracts + 0.01)
        self.assertAlmostEqual(recommendation.breakeven, recommendation.long_leg.strike + recommendation.net_debit)

    def test_holds_when_amount_too_small(self):
        recommendation = evaluate_bull_call_spread(
            self.config, self.account, spot=100.0, expiry="20270115", legs=self.legs,
            target_price=108.0, target_date="2027-01-01", amount=1.0,
        )
        self.assertEqual(recommendation.action, "HOLD")


class ExitPlanTests(unittest.TestCase):
    def test_exit_by_date_is_before_expiry(self):
        config = BullCallSpreadConfig()
        expiry = "20270115"
        plan = build_exit_plan(config, net_debit=3.0, expiry=expiry)
        expiry_date = datetime.strptime(expiry, "%Y%m%d").date()
        exit_date = datetime.strptime(plan.exit_by_date, "%Y-%m-%d").date()
        self.assertEqual(exit_date, expiry_date - timedelta(days=config.exit_days_before_expiry))
        self.assertAlmostEqual(plan.stop_loss_debit_value, 3.0 * config.stop_loss_pct_of_debit)


if __name__ == "__main__":
    unittest.main()
