import unittest

from goldtrading.carry import basis, round_to_tick, theoretical_calendar_spread, theoretical_futures_price


class CarryMathTests(unittest.TestCase):
    def test_theoretical_futures_price_adds_carry_cost_over_time(self):
        price = theoretical_futures_price(spot=2000.0, financing_rate_annual=0.05, storage_rate_annual=0.0, convenience_yield_annual=0.0, days_to_expiry=365)
        self.assertAlmostEqual(price, 2100.0, places=2)

    def test_theoretical_futures_price_at_zero_days_equals_spot(self):
        price = theoretical_futures_price(spot=2000.0, financing_rate_annual=0.05, storage_rate_annual=0.003, convenience_yield_annual=0.0, days_to_expiry=0)
        self.assertAlmostEqual(price, 2000.0, places=2)

    def test_basis_is_market_minus_theoretical(self):
        self.assertAlmostEqual(basis(2110.0, 2100.0), 10.0, places=2)

    def test_calendar_spread_widens_with_more_time(self):
        spread = theoretical_calendar_spread(spot=2000.0, financing_rate_annual=0.05, storage_rate_annual=0.0, convenience_yield_annual=0.0, near_days_to_expiry=30, far_days_to_expiry=120)
        self.assertAlmostEqual(spread, 2000.0 * 0.05 * (90 / 365), places=2)

    def test_round_to_tick(self):
        self.assertAlmostEqual(round_to_tick(2000.07, 0.10), 2000.10, places=2)
        self.assertAlmostEqual(round_to_tick(2000.04, 0.10), 2000.00, places=2)


if __name__ == "__main__":
    unittest.main()
