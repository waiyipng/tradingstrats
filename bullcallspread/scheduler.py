"""Automated read-only MS bull call spread research scheduler.

Runs every 30 minutes: refreshes unrealized P&L for any open position (via
monitor.py) and generates a fresh recommendation against the configured
target price/date/amount. This scheduler never places an order itself -
execution stays a manual, explicit `--confirm` action via run_bullcallspread.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from newstrading.common import load_json, save_json, utcnow_iso
from trading_config import get_strategy_config
from bullcallspread.analyst_agent import run_analyst_agent
from bullcallspread.config import MS_CONFIG
from bullcallspread.consensus import fetch_consensus
from bullcallspread.ibkr_data import fetch_recommendation_inputs
from bullcallspread.monitor import run_monitor_cycle
from bullcallspread.schedule import scan_trigger
from bullcallspread.strategy import evaluate_bull_call_spread
from bullcallspread.trading_agent import run_trading_agent

_CFG = get_strategy_config("bullcallspread")
RUN_INTERVAL_MINUTES = _CFG["run_interval_minutes"]
CLIENT_ID = 48

# This scheduler never submits orders (execution stays a manual --confirm action via
# run_earnings_strategy.py / run_bullcallspread.py), but the quote/account data it reads
# should reflect live vs paper. Live still requires BOTH mode="live" in
# trading_config.json AND this env var, matching the other strategies' gate.
LIVE_CONFIRM_ENV = "BULLCALLSPREAD_LIVE_CONFIRM"
USE_LIVE_IBKR = _CFG["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"

LOG_PATH = Path(__file__).resolve().parent / "bullcallspread_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"
EARNINGS_VIEW_PATH = Path(__file__).resolve().parent / "my_earnings_view.json"
ANALYST_CACHE_PATH = Path(__file__).resolve().parent / "data" / "analyst_prediction_cache.json"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s bullcallspread-scheduler - %(message)s")
logger = logging.getLogger("bullcallspread-scheduler")

if _CFG["mode"] == "live" and not USE_LIVE_IBKR:
    logger.warning(
        "trading_config.json requests mode=live for bullcallspread but %s is not set to '1'; "
        "staying on paper trading.", LIVE_CONFIRM_ENV,
    )


def _get_analyst_prediction(earnings_view: dict, consensus):
    """Re-runs the analyst agent only when the earnings view file's contents change,
    since it's an LLM call that should not fire every 30-minute scheduler cycle."""
    view_hash = hashlib.sha256(json.dumps(earnings_view, sort_keys=True).encode("utf-8")).hexdigest()
    if ANALYST_CACHE_PATH.exists():
        cached = load_json(ANALYST_CACHE_PATH)
        if cached.get("view_hash") == view_hash:
            prediction = cached["prediction"]
            from bullcallspread.models import AnalystPrediction

            return AnalystPrediction(**prediction)

    prediction = run_analyst_agent(
        earnings_view["predicted_net_income_usd_billion"], earnings_view["quarter"],
        earnings_view.get("confidence_pct", 100), earnings_view.get("notes", ""), consensus,
        earnings_view.get("predicted_net_revenue_usd_billion"),
    )
    save_json(ANALYST_CACHE_PATH, {"view_hash": view_hash, "prediction": prediction.to_dict()})
    return prediction


def _run_agentic_cycle() -> dict[str, object]:
    with open(EARNINGS_VIEW_PATH, "r", encoding="utf-8") as fh:
        earnings_view = json.load(fh)
    consensus = fetch_consensus(MS_CONFIG.symbol)
    if not consensus.next_earnings_date:
        raise RuntimeError(f"no upcoming earnings date found for {MS_CONFIG.symbol}")

    analyst_prediction = _get_analyst_prediction(earnings_view, consensus)
    target_date = datetime.strptime(consensus.next_earnings_date, "%Y-%m-%d").date()
    account, spot, expiry, legs = fetch_recommendation_inputs(MS_CONFIG, target_date, CLIENT_ID, live=USE_LIVE_IBKR)
    trading_report = run_trading_agent(MS_CONFIG, analyst_prediction, account, spot, expiry, legs, MS_CONFIG.default_amount_usd)
    return {
        "account": account.__dict__,
        "spot_price": spot,
        "analyst_prediction": analyst_prediction.to_dict(),
        "trading_agent": trading_report.to_dict(),
        "bull_call_spread": trading_report.recommendation.to_dict(),
    }


def _run_static_cycle() -> dict[str, object]:
    target_date = datetime.strptime(MS_CONFIG.target_date, "%Y-%m-%d").date()
    account, spot, expiry, legs = fetch_recommendation_inputs(MS_CONFIG, target_date, CLIENT_ID, live=USE_LIVE_IBKR)
    recommendation = evaluate_bull_call_spread(
        MS_CONFIG, account, spot, expiry, legs, MS_CONFIG.target_price, MS_CONFIG.target_date, MS_CONFIG.default_amount_usd
    )
    return {"account": account.__dict__, "spot_price": spot, "bull_call_spread": recommendation.to_dict()}


def run_cycle() -> None:
    is_agentic = EARNINGS_VIEW_PATH.exists()
    mode = "agentic_automated" if is_agentic else "research_only_automated"
    if USE_LIVE_IBKR:
        mode = f"live_{mode}"
    payload: dict[str, object] = {"generated_at": utcnow_iso(), "mode": mode}
    try:
        payload["monitor"] = run_monitor_cycle(MS_CONFIG, CLIENT_ID, live=USE_LIVE_IBKR)
        payload.update(_run_agentic_cycle() if is_agentic else _run_static_cycle())
    except (TimeoutError, RuntimeError) as exc:
        payload.update({"status": "data_unavailable", "reason": str(exc) or "IBKR market-data request timed out"})

    path = OUTPUT_DIR / f"bullcallspread_run_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(path, payload)
    logger.info("bullcallspread cycle -> %s", json.dumps(payload, default=str))


def main() -> None:
    logger.info("Starting automated MS bull call spread research scheduler every %d minutes, Mon-Fri 9:30am-4:00pm ET only (research only; no auto-execution)", RUN_INTERVAL_MINUTES)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, scan_trigger(RUN_INTERVAL_MINUTES), id="bullcallspread_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()
