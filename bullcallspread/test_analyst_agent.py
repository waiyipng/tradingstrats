import unittest

from bullcallspread.analyst_agent import HIGH_CONFIDENCE_THRESHOLD_PCT, _build_user_prompt
from bullcallspread.consensus import ConsensusSnapshot, EarningsHistoryQuarter


def _consensus(**overrides):
    defaults = dict(
        symbol="MS",
        current_price=190.31,
        next_earnings_date="2026-10-14",
        consensus_eps=3.03,
        eps_low=2.86,
        eps_high=3.20,
        revenue_low=19_846_711_430,
        revenue_high=21_485_000_000,
        revenue_average=20_468_094_700,
        shares_outstanding=1_570_566_292,
        analyst_target_mean=233.43,
        analyst_target_median=243.0,
        analyst_target_low=184.0,
        analyst_target_high=262.0,
        history=[EarningsHistoryQuarter("2026-07-15", 2.93, 3.46, 17.94)],
    )
    defaults.update(overrides)
    return ConsensusSnapshot(**defaults)


class BuildUserPromptTests(unittest.TestCase):
    def test_implied_eps_and_surprise_are_computed_from_net_income(self):
        consensus = _consensus()
        prompt = _build_user_prompt(5.6, "2026Q3", 100, "", consensus)
        # $5.6B / 1,570,566,292 shares = $3.57 EPS, a ~17.8% implied beat vs $3.03 consensus
        self.assertIn("implied EPS $3.57", prompt)
        self.assertIn("17.8%", prompt)

    def test_handles_missing_shares_outstanding(self):
        consensus = _consensus(shares_outstanding=None)
        prompt = _build_user_prompt(5.6, "2026Q3", 100, "", consensus)
        self.assertIn("implied EPS $None", prompt)

    def test_includes_user_notes_and_history(self):
        consensus = _consensus()
        prompt = _build_user_prompt(5.6, "2026Q3", 100, "wealth management tailwind", consensus)
        self.assertIn("wealth management tailwind", prompt)
        self.assertIn("2026-07-15", prompt)

    def test_high_confidence_instructs_agent_to_treat_forecast_as_fact(self):
        consensus = _consensus()
        prompt = _build_user_prompt(5.6, "2026Q3", HIGH_CONFIDENCE_THRESHOLD_PCT, "", consensus)
        self.assertIn("Treat this net-income figure as a known fact", prompt)
        self.assertIn(f"confidence {HIGH_CONFIDENCE_THRESHOLD_PCT}%", prompt)

    def test_low_confidence_instructs_agent_to_hedge(self):
        consensus = _consensus()
        prompt = _build_user_prompt(5.6, "2026Q3", 60, "", consensus)
        self.assertIn("treat it as one", prompt)
        self.assertNotIn("Treat this net-income figure as a known fact", prompt)


if __name__ == "__main__":
    unittest.main()
