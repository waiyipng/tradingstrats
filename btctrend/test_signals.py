import unittest
from unittest import mock

import numpy as np
import pandas as pd

from btctrend.backtest import banded_positions, strategy_returns
from btctrend.config import BTC_CONFIG
from btctrend.signals import apply_band, latest_signal, min_history_bars, signal_votes, target_exposure_series


def _bars(closes):
    index = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=index, dtype=float)
    # Zero intraday range, so a channel breakout is decided by closes alone.
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close})


def _trend(start, daily_return, days, wiggle=0.02):
    # Alternating wiggle keeps realized volatility realistic and non-zero.
    returns = np.full(days, daily_return) + np.where(np.arange(days) % 2 == 0, wiggle, -wiggle)
    return list(start * np.cumprod(1 + returns))


class SignalTests(unittest.TestCase):
    def test_steady_uptrend_votes_fully_long(self):
        signal = latest_signal(_bars(_trend(20_000, 0.004, 300)), BTC_CONFIG)
        self.assertEqual(signal.score, 1.0)
        self.assertTrue(all(vote.long for vote in signal.votes))
        self.assertEqual(len(signal.votes), 9)

    def test_steady_downtrend_votes_flat(self):
        signal = latest_signal(_bars(_trend(60_000, -0.004, 300)), BTC_CONFIG)
        self.assertEqual(signal.score, 0.0)
        self.assertEqual(signal.target_exposure, 0.0)

    def test_high_volatility_scales_exposure_down(self):
        calm = latest_signal(_bars(_trend(20_000, 0.004, 300, wiggle=0.01)), BTC_CONFIG)
        wild = latest_signal(_bars(_trend(20_000, 0.004, 300, wiggle=0.06)), BTC_CONFIG)
        self.assertEqual(calm.target_exposure, 1.0)
        self.assertLess(wild.target_exposure, 0.6)
        self.assertAlmostEqual(wild.target_exposure, wild.vol_scalar, places=3)

    def test_insufficient_history_raises(self):
        with self.assertRaises(RuntimeError):
            latest_signal(_bars(_trend(20_000, 0.004, min_history_bars(BTC_CONFIG) - 1)), BTC_CONFIG)

    def test_signal_uses_no_future_data(self):
        bars = _bars(_trend(20_000, 0.004, 300))
        full = target_exposure_series(bars, BTC_CONFIG)
        truncated = target_exposure_series(bars.iloc[:250], BTC_CONFIG)
        pd.testing.assert_series_equal(full.iloc[:250], truncated)

    def test_donchian_holds_state_between_channels(self):
        trend = _trend(20_000, 0.004, 200, wiggle=0.0)
        closes = trend + [trend[-1]] * 40
        votes = signal_votes(_bars(closes), BTC_CONFIG)
        # Flat-lining after a breakout neither breaks out nor breaks down: stays long.
        self.assertEqual(votes["donchian55/20"].iloc[-1], 1.0)


class HistoryFillTests(unittest.TestCase):
    def test_missing_completed_days_are_filled_from_coinbase(self):
        from datetime import date

        from btctrend import history

        bars = _bars([100.0, 101.0])  # 2024-01-01, 2024-01-02
        response = mock.Mock()
        response.json.return_value = [
            [int(pd.Timestamp("2024-01-04").timestamp()), 1, 2, 1, 104.0, 0],  # today: partial, dropped
            [int(pd.Timestamp("2024-01-03").timestamp()), 1, 2, 1, 103.0, 0],
        ]
        with mock.patch.object(history.requests, "get", return_value=response):
            filled = history._fill_recent_from_coinbase(bars, date(2024, 1, 4))
        self.assertEqual(list(filled["close"]), [100.0, 101.0, 103.0])

    def test_coinbase_failure_leaves_bars_unchanged(self):
        from datetime import date

        from btctrend import history

        bars = _bars([100.0, 101.0])
        with mock.patch.object(history.requests, "get", side_effect=history.requests.ConnectionError("down")):
            self.assertEqual(len(history._fill_recent_from_coinbase(bars, date(2024, 1, 4))), 2)


class BandTests(unittest.TestCase):
    def test_exit_always_executes(self):
        self.assertEqual(apply_band(0.0, 0.1, 0.2), 0.0)

    def test_small_change_is_ignored(self):
        self.assertEqual(apply_band(0.55, 0.4, 0.2), 0.4)

    def test_large_change_executes(self):
        self.assertEqual(apply_band(0.7, 0.4, 0.2), 0.7)

    def test_small_entry_from_flat_waits(self):
        self.assertEqual(apply_band(0.15, 0.0, 0.2), 0.0)


class BacktestMechanicsTests(unittest.TestCase):
    def test_position_lags_signal_by_one_bar_and_charges_costs(self):
        close = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2024-01-01", periods=3))
        held = pd.Series([1.0, 1.0, 1.0], index=close.index)
        returns, position = strategy_returns(close, held, cost_per_side=0.01)
        self.assertEqual(list(position), [0.0, 1.0, 1.0])
        self.assertAlmostEqual(returns.iloc[1], 0.10 - 0.01)
        self.assertAlmostEqual(returns.iloc[2], 0.10)

    def test_banded_positions(self):
        targets = pd.Series([0.1, 0.3, 0.4, 0.45, 0.0])
        self.assertEqual(list(banded_positions(targets, 0.2)), [0.0, 0.3, 0.3, 0.3, 0.0])


if __name__ == "__main__":
    unittest.main()
