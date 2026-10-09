import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from btctrend.config import BTC_CONFIG
from btctrend.models import AccountState, BtcQuote, SignalVote, TrendSignal
from btctrend.state import _default_state, apply_fill
from btctrend import execution, state as state_module
from btctrend.execution import reconcile_fills, round_to_tick
from btctrend.strategy import evaluate_rebalance, round_down


def _signal(target, close=60_000.0, atr=2_000.0, breakout=65_000.0):
    return TrendSignal(
        bar_date="2026-10-02", close=close, votes=[SignalVote("close>sma50", True, "close vs SMA50")],
        score=target, realized_vol_annual=0.45, vol_scalar=1.0, target_exposure=target,
        return_30d_pct=5.0, drawdown_from_high_pct=-20.0, atr=atr, reentry_breakout_level=breakout,
    )


ACCOUNT = AccountState(cash=1_000_000.0, net_liquidation=1_000_000.0, excess_liquidity=1_000_000.0)  # sleeve = $100,000
QUOTE = BtcQuote(bid=59_990.0, ask=60_010.0)


def _state(**overrides):
    state = _default_state()
    state.update(overrides)
    return state


class EvaluateRebalanceTests(unittest.TestCase):
    def test_entry_buys_target_fraction_of_sleeve(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.5), ACCOUNT, QUOTE, _state(), 0.0)
        self.assertEqual(rec.action, "BUY")
        self.assertAlmostEqual(rec.target_qty, round_down(50_000 / 60_000, 0.0001))
        self.assertEqual(rec.limit_price, round(60_010 * 1.005, 2))
        self.assertEqual(rec.new_held_exposure, 0.5)

    def test_within_band_holds(self):
        state = _state(btc_qty=0.8333, held_exposure=0.5, target_qty=0.8333)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.6), ACCOUNT, QUOTE, state, 0.8333)
        self.assertEqual(rec.action, "HOLD")

    def test_price_drift_does_not_resize_inside_band(self):
        state = _state(btc_qty=0.8333, held_exposure=0.5, target_qty=0.8333)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.5, close=80_000), ACCOUNT, BtcQuote(79_990, 80_010), state, 0.8333)
        self.assertEqual(rec.action, "HOLD")

    def test_partial_fill_remainder_is_retried(self):
        state = _state(btc_qty=0.5, held_exposure=0.5, target_qty=0.8333)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.5), ACCOUNT, QUOTE, state, 0.5)
        self.assertEqual(rec.action, "BUY")
        self.assertAlmostEqual(rec.order_qty, 0.3333)

    def test_exit_sells_everything_owned(self):
        state = _state(btc_qty=0.8, held_exposure=0.5, target_qty=0.8)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.0), ACCOUNT, QUOTE, state, 0.8)
        self.assertEqual(rec.action, "SELL")
        self.assertAlmostEqual(rec.order_qty, 0.8)
        self.assertEqual(rec.limit_price, round(59_990 * 0.995, 2))

    def test_never_sells_btc_the_strategy_does_not_own(self):
        state = _state(btc_qty=0.0, held_exposure=0.0, target_qty=0.0)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.0), ACCOUNT, QUOTE, state, 2.0)  # external BTC in the account
        self.assertEqual(rec.action, "HOLD")

    def test_sell_capped_at_account_holding(self):
        state = _state(btc_qty=0.8, held_exposure=0.5, target_qty=0.8)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.0), ACCOUNT, QUOTE, state, 0.3)
        self.assertAlmostEqual(rec.order_qty, 0.3)

    def test_buy_limited_by_cash_reserve(self):
        account = AccountState(cash=60_000.0, net_liquidation=1_000_000.0, excess_liquidity=1_000_000.0)  # 5% reserve = $50,000
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), account, QUOTE, _state(), 0.0)
        self.assertEqual(rec.action, "BUY")
        self.assertLessEqual(rec.order_notional, 10_000.0)

    def test_bad_quote_is_rejected(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), ACCOUNT, BtcQuote(39_990, 40_010), _state(), 0.0)
        self.assertEqual(rec.action, "HOLD")
        self.assertIn("deviates", rec.reasons[-1])

    def test_missing_quote_holds(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), ACCOUNT, BtcQuote(None, None), _state(), 0.0)
        self.assertEqual(rec.action, "HOLD")


class ProfitTakingTests(unittest.TestCase):
    # Entry at 50,000: the +50% trigger is a close at or above 75,000. Wide ATR keeps the stop out of the way.
    HOLDING = dict(btc_qty=1.6666, held_exposure=1.0, target_qty=1.6666, peak_close=76_000.0, entry_price=50_000.0)

    def test_trim_fires_once_close_is_50pct_above_entry(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=76_000, atr=1_000), ACCOUNT, BtcQuote(75_990, 76_010), _state(**self.HOLDING), 1.6666)
        self.assertTrue(rec.profit_taken)
        self.assertEqual(rec.action, "SELL")
        self.assertAlmostEqual(rec.new_held_exposure, 2 / 3, places=4)

    def test_no_trim_below_threshold(self):
        state = _state(**{**self.HOLDING, "peak_close": 70_000.0})  # stop at 66,000, well below the bid
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=70_000, atr=1_000), ACCOUNT, BtcQuote(69_990, 70_010), state, 1.6666)
        self.assertFalse(rec.profit_taken)
        self.assertEqual(rec.action, "HOLD")

    def test_trimmed_trade_is_not_topped_back_up(self):
        state = _state(btc_qty=1.1, held_exposure=2 / 3, target_qty=1.1, peak_close=80_000.0, entry_price=50_000.0, profit_taken=True)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=80_000, atr=1_000), ACCOUNT, BtcQuote(79_990, 80_010), state, 1.1)
        self.assertEqual(rec.action, "HOLD")
        self.assertTrue(rec.profit_taken)

    def test_new_entry_resets_entry_price_and_trim(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), ACCOUNT, QUOTE, _state(profit_taken=True, entry_price=10_000.0), 0.0)
        self.assertEqual(rec.action, "BUY")
        self.assertEqual(rec.entry_price, 60_000.0)
        self.assertFalse(rec.profit_taken)

    def test_risk_at_stop_is_reported(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), ACCOUNT, QUOTE, _state(), 0.0)
        # 1.6666 BTC x (60,000 mid - (60,000 - 4 x 2,000)) = ~13,333, 1.33% of net liq
        self.assertAlmostEqual(rec.risk_at_stop_usd, 13_332.8, places=0)
        self.assertAlmostEqual(rec.risk_at_stop_pct_of_net_liq, 0.0133, places=4)


class StaleDataTests(unittest.TestCase):
    def test_stale_data_blocks_entries(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0), ACCOUNT, QUOTE, _state(), 0.0, data_stale=True)
        self.assertEqual(rec.action, "HOLD")
        self.assertIn("increases blocked", " ".join(rec.reasons))

    def test_stale_data_still_allows_exits(self):
        state = _state(btc_qty=0.8, held_exposure=0.5, target_qty=0.8, peak_close=60_000.0, entry_price=58_000.0)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.0), ACCOUNT, QUOTE, state, 0.8, data_stale=True)
        self.assertEqual(rec.action, "SELL")


def _exec_fill(exec_id, side, shares, price, client_id=49, commission=1.5, symbol="BTC"):
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol),
        execution=SimpleNamespace(execId=exec_id, side=side, shares=shares, price=price, orderId=7, clientId=client_id, time=datetime.now(timezone.utc)),
        commissionReport=SimpleNamespace(commission=commission),
    )


class ReconcileFillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(state_module, "STATE_PATH", Path(self.tmp.name) / "state.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_records_new_strategy_fills_once_and_ignores_others(self):
        ib = mock.Mock()
        ib.reqExecutions.return_value = [
            _exec_fill("a1", "BOT", 0.5, 60_000),
            _exec_fill("a2", "BOT", 0.5, 62_000, commission=1e308),  # unset commission sentinel
            _exec_fill("x1", "BOT", 3.0, 61_000, client_id=22),       # another strategy's client id
            _exec_fill("e1", "BOT", 1.0, 3_000, symbol="ETH"),
        ]
        self.assertEqual(len(reconcile_fills(ib, BTC_CONFIG)), 2)
        self.assertEqual(reconcile_fills(ib, BTC_CONFIG), [])  # idempotent by execId
        state = state_module.load_state()
        self.assertAlmostEqual(state["btc_qty"], 1.0)
        self.assertAlmostEqual(state["avg_cost"], (30_000 + 1.5 + 31_000) / 1.0)

    def test_save_is_atomic_and_round_trips(self):
        state = state_module.load_state()
        state["btc_qty"] = 0.25
        state_module.save_state(state)
        self.assertFalse(state_module.STATE_PATH.with_suffix(".json.tmp").exists())
        self.assertEqual(state_module.load_state()["btc_qty"], 0.25)


class TickRoundingTests(unittest.TestCase):
    def test_buy_rounds_up_and_sell_rounds_down_to_tick(self):
        self.assertEqual(round_to_tick(85_240.91, 0.25, "BUY"), 85_241.0)
        self.assertEqual(round_to_tick(84_391.66, 0.25, "SELL"), 84_391.5)
        self.assertEqual(round_to_tick(85_241.00, 0.25, "BUY"), 85_241.0)


class FillAccountingTests(unittest.TestCase):
    def test_average_cost_and_realized_pnl(self):
        state = _default_state()
        apply_fill(state, "BUY", 1.0, 50_000, 1)
        apply_fill(state, "BUY", 1.0, 70_000, 2)
        self.assertAlmostEqual(state["avg_cost"], 60_000)
        realized = apply_fill(state, "SELL", 1.0, 66_000, 3)
        self.assertAlmostEqual(realized, 6_000)
        self.assertAlmostEqual(state["btc_qty"], 1.0)
        apply_fill(state, "SELL", 1.0, 54_000, 4)
        self.assertAlmostEqual(state["realized_pnl"], 0.0)
        self.assertEqual(state["btc_qty"], 0.0)

    def test_commissions_reduce_realized_pnl(self):
        state = _default_state()
        apply_fill(state, "BUY", 1.0, 50_000, 1, commission=90)
        realized = apply_fill(state, "SELL", 1.0, 60_000, 2, commission=110)
        self.assertAlmostEqual(realized, 10_000 - 90 - 110)


class TrailingStopTests(unittest.TestCase):
    # Peak close 70,000 - 4 x ATR 2,000 = stop at 62,000.
    HOLDING = dict(btc_qty=0.8, held_exposure=0.5, target_qty=0.8, peak_close=70_000.0)

    def test_stop_hit_exits_and_locks(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=63_000), ACCOUNT, BtcQuote(61_900, 61_950), _state(**self.HOLDING), 0.8)
        self.assertTrue(rec.stop_triggered)
        self.assertEqual(rec.stop_price, 62_000.0)
        self.assertEqual(rec.action, "SELL")
        self.assertAlmostEqual(rec.order_qty, 0.8)
        self.assertTrue(rec.reentry_locked)

    def test_above_stop_keeps_position_and_ratchets_peak(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.5, close=72_000, breakout=71_000), ACCOUNT, BtcQuote(71_990, 72_010), _state(**self.HOLDING), 0.8)
        self.assertFalse(rec.stop_triggered)
        self.assertEqual(rec.action, "HOLD")
        self.assertEqual(rec.peak_close, 72_000.0)
        self.assertEqual(rec.stop_price, 64_000.0)

    def test_lock_blocks_reentry_without_breakout(self):
        state = _state(stop_locked=True)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=60_000, breakout=65_000), ACCOUNT, QUOTE, state, 0.0)
        self.assertEqual(rec.action, "HOLD")
        self.assertTrue(rec.reentry_locked)

    def test_breakout_lifts_lock_and_reenters(self):
        state = _state(stop_locked=True)
        rec = evaluate_rebalance(BTC_CONFIG, _signal(1.0, close=60_000, breakout=59_000), ACCOUNT, QUOTE, state, 0.0)
        self.assertEqual(rec.action, "BUY")
        self.assertFalse(rec.reentry_locked)
        self.assertEqual(rec.peak_close, 60_000.0)

    def test_signal_exit_still_works_without_stop(self):
        rec = evaluate_rebalance(BTC_CONFIG, _signal(0.0, close=68_000), ACCOUNT, BtcQuote(67_990, 68_010), _state(**self.HOLDING), 0.8)
        self.assertFalse(rec.stop_triggered)
        self.assertEqual(rec.action, "SELL")


if __name__ == "__main__":
    unittest.main()
