"""One BTC trend cycle: completed daily bars -> ensemble signal -> IBKR account/quote ->
fill reconciliation -> rebalance recommendation (signal exits, trailing ATR stop,
profit trim) -> optional paper execution."""
from __future__ import annotations

from typing import Any

from newstrading.common import utcnow_iso
from btctrend.approval import clear_pending, is_expired, load_pending, save_pending
from btctrend.config import BtcTrendConfig
from btctrend.execution import commit_cycle_state, reconcile_fills
from btctrend.history import bar_age_days, fetch_daily_bars
from btctrend.ibkr_data import account_btc_qty, account_state, btc_contract, btc_quote_with_fallback, connect
from btctrend.signals import latest_signal
from btctrend.state import load_state
from btctrend.strategy import evaluate_rebalance


def run_cycle(config: BtcTrendConfig, client_id: int, execute: bool, live: bool = False) -> dict[str, Any]:
    mode = "research_only"
    if execute:
        mode = "live_automated" if live else "paper_automated"
    payload: dict[str, Any] = {"generated_at": utcnow_iso(), "mode": mode}
    try:
        bars = fetch_daily_bars(config.history_symbol, lookback_days=config.history_days)
        signal = latest_signal(bars, config)
        age = bar_age_days(bars)
        payload["signal"] = signal.to_dict()
        payload["data"] = {"last_bar": signal.bar_date, "bar_age_days": age, "stale": age > config.max_bar_age_days}

        ib = connect(client_id, live=live)
        try:
            account = account_state(ib)
            contract, increment, price_tick = btc_contract(ib, config)
            quote = btc_quote_with_fallback(ib, contract)
            held_in_account = account_btc_qty(ib, config)
            if execute:
                payload["reconciled_fills"] = reconcile_fills(ib, config)
            recommendation = evaluate_rebalance(
                config, signal, account, quote, load_state(), held_in_account, increment, data_stale=age > config.max_bar_age_days
            )
            if not execute:
                execution = {"status": "SKIPPED", "reason": "research only"}
            elif recommendation.action == "HOLD":
                clear_pending()  # a flattened signal drops any stale pending order
                execution = {"status": "SKIPPED", "reason": "no actionable rebalance"}
            else:
                # Orders are never submitted automatically: a human must approve this
                # recommendation (e.g. from the dashboard) before anything reaches IBKR.
                pending = load_pending()
                if pending is not None and is_expired(pending):
                    clear_pending()
                    pending = None
                if pending is None:
                    pending = save_pending(recommendation)
                execution = {"status": "PENDING_APPROVAL", "reason": f"awaiting human approval (expires {pending['expires_at']})"}
            if execute:
                # Risk state (trailing-stop peak, re-entry lock, profit-trim flag) tracks
                # live price every cycle regardless of approval status; only the traded
                # quantity itself waits for a human to approve the order.
                commit_cycle_state(recommendation, order_placed=recommendation.action != "HOLD")
        finally:
            if ib.isConnected():
                ib.disconnect()

        payload.update(
            {
                "account": account.__dict__,
                "quote": {"bid": quote.bid, "ask": quote.ask, "last": quote.last, "source": quote.source},
                "account_btc_qty": held_in_account,
                "recommendation": recommendation.to_dict(),
                "execution": execution,
            }
        )
    except (TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
        payload.update({"status": "data_unavailable", "reason": str(exc) or "IBKR or history request timed out"})
    except Exception as exc:  # never let one bad cycle stop the scheduler or skip its run record
        payload.update({"status": "error", "reason": f"{type(exc).__name__}: {exc}"})
    return payload
