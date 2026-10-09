"""APScheduler orchestrator for the newstrading 4-stage JSON pipeline.

Mirrors optiontrading/scheduler.py: runs each stage as a subprocess of the
current Python interpreter, chaining sourcing -> signaling ->
order_recommendation -> execution once per watchlist symbol on a schedule.

Default behavior is DRY-RUN (paper broker, no live IBKR orders). Set EXECUTE=True
and BROKER="ibkr" below only after validating dry runs.

Usage:
    python -m newstrading.scheduler
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

try:
    import pytz
    TZ = pytz.timezone("US/Eastern")
except Exception:
    TZ = None

from newstrading.config.loader import all_symbols
from newstrading.audit import create_run, prune_expired_runs
from newstrading.common import new_id
from newstrading.order_recommendation.batch_allocation import allocate_run

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduler.log")

from trading_config import get_strategy_config

# ---------------------------------------------------------------------------
# CONFIG - broker mode and run cadence come from trading_config.json
# ---------------------------------------------------------------------------
_CFG = get_strategy_config("newstrading")
BROKER = "ibkr"        # "paper" or "ibkr"
EXECUTE = True          # only used when BROKER == "ibkr"; gates live order submission
USE_LIVE_IBKR = _CFG["mode"] == "live"  # driven by trading_config.json; must stay False unless the user explicitly requests live trading
RUN_INTERVAL_MINUTES = _CFG["run_interval_minutes"]
SYMBOL_STAGGER_SECONDS = 5  # avoid bursting free-tier news APIs / IBKR pacing limits
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 10

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("newstrading-scheduler")


def run_stage(module: str, extra_args: list) -> int:
    cmd = [PYTHON, "-m", module, *extra_args]
    attempt = 0
    while True:
        attempt += 1
        logger.info("Starting: %s (attempt %d)", " ".join(cmd), attempt)
        try:
            proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
            if proc.stdout:
                logger.info("STDOUT:\n%s", proc.stdout)
            if proc.stderr:
                logger.warning("STDERR:\n%s", proc.stderr)
            if proc.returncode == 0:
                return 0
            raise RuntimeError(f"{module} exited {proc.returncode}")
        except Exception as exc:
            logger.exception("Stage failed on attempt %d: %s", attempt, exc)
            if attempt >= MAX_RETRIES:
                logger.error("Max retries reached for: %s", module)
                return 1
            time.sleep(RETRY_BASE_SECONDS * (2 ** (attempt - 1)))


def run_pipeline_for_symbol(symbol: str, audit_run_id: str) -> bool:
    logger.info("Running pipeline for %s", symbol)

    if run_stage("newstrading.sourcing.run_sourcing", ["--symbol", symbol, "--audit-run-id", audit_run_id]) != 0:
        return False
    if run_stage("newstrading.signaling.run_signaling", ["--symbol", symbol, "--audit-run-id", audit_run_id]) != 0:
        return False

    order_rec_args = ["--symbol", symbol, "--client-id", "21", "--audit-run-id", audit_run_id]
    if BROKER == "ibkr" and USE_LIVE_IBKR:
        order_rec_args.append("--live")
    if run_stage("newstrading.order_recommendation.run_order_recommendation", order_rec_args) != 0:
        return False
    return True


def pipeline_job() -> None:
    audit_run_id = new_id("audit")
    create_run(audit_run_id)
    pruned = prune_expired_runs()
    logger.info("Starting audit run %s; pruned %d expired audit record(s)", audit_run_id, pruned)
    for symbol in all_symbols():
        run_pipeline_for_symbol(symbol, audit_run_id)
        time.sleep(SYMBOL_STAGGER_SECONDS)
    allocated_recommendations = allocate_run(audit_run_id, live=USE_LIVE_IBKR, client_id=22)
    logger.info("Allocation plan selected %d recommendation(s)", len(allocated_recommendations))
    for recommendation_path in allocated_recommendations:
        execution_args = ["--recommendation-file", str(recommendation_path), "--broker", BROKER, "--client-id", "22", "--audit-run-id", audit_run_id]
        if BROKER == "ibkr":
            if USE_LIVE_IBKR:
                execution_args.append("--live")
            if EXECUTE:
                execution_args.append("--execute")
        run_stage("newstrading.execution.run_execution", execution_args)
    if BROKER == "ibkr" and EXECUTE:
        monitor_args = ["--client-id", "22"]
        if USE_LIVE_IBKR:
            monitor_args.append("--live")
        run_stage("newstrading.execution.position_monitor", monitor_args)


def main() -> None:
    logger.info("Starting newstrading scheduler; broker=%s; execute=%s; live=%s", BROKER, EXECUTE, USE_LIVE_IBKR)
    sched = BlockingScheduler(timezone=TZ) if TZ else BlockingScheduler()
    trigger = IntervalTrigger(minutes=RUN_INTERVAL_MINUTES, timezone=TZ)
    sched.add_job(pipeline_job, trigger, id="newstrading_pipeline", max_instances=1, replace_existing=True)
    logger.info("Scheduled newstrading_pipeline every %d minute(s)", RUN_INTERVAL_MINUTES)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
