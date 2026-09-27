import json
import tempfile
import unittest
from pathlib import Path

from optiontrading.wheel_strategy import Proposal, add_proposal, choose_strike, load_state, reject


class WheelStrategyTests(unittest.TestCase):
    def test_put_strike_is_highest_eligible_otm_strike(self):
        self.assertEqual(choose_strike([550, 570, 590, 600], 630, "P", 5), 590)

    def test_call_strike_is_lowest_eligible_otm_strike(self):
        self.assertEqual(choose_strike([650, 660, 680, 700], 630, "C", 5), 680)

    def test_reject_persists_without_submitting(self):
        proposal = Proposal(
            proposal_id="wheel_test", created_at="2026-09-20T00:00:00+00:00",
            symbol="VOO", phase="PUT", action="SELL", right="P", expiration="20261020",
            strike=600, quantity=1, limit_price=2.5, collateral=60000,
            rationale="test",
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            add_proposal(state_path, proposal)
            rejected = reject(state_path, "wheel_test")
            self.assertEqual(rejected["status"], "REJECTED")
            self.assertEqual(load_state(state_path)["proposals"][0]["status"], "REJECTED")
            self.assertEqual(json.loads(state_path.read_text())["proposals"][0]["order_id"], None)


if __name__ == "__main__":
    unittest.main()