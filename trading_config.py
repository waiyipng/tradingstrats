"""Loader for trading_config.json: per-strategy broker mode and scheduler cadence.

Each strategy's scheduler reads its settings here instead of hardcoding them, so
live-vs-paper routing and run frequency are controlled from one file.

Every strategy now has an implemented live-IBKR routing path (connecting to IBKR's
live port 7496 instead of paper port 7497). Setting mode="live" in trading_config.json
is necessary but NOT sufficient to actually submit live orders: each scheduler and
manual CLI also requires a matching per-strategy environment variable
(e.g. WHEELTRADING_LIVE_CONFIRM=1) to be set to "1" on the process itself before it will
treat mode="live" as live rather than silently staying on paper. This two-factor gate
(config file + environment variable) means a stray edit to trading_config.json alone can
never flip an already-running, unattended scheduler to live trading — see each
strategy's scheduler.py for the exact env var name and the gate check.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "trading_config.json"

# Strategies that have a real live-trading code path (USE_LIVE_IBKR or equivalent).
STRATEGIES_WITH_LIVE_PATH = {"newstrading", "wheeltrading", "goldtrading", "bullcallspread", "btctrend"}

# Defaults mirror each strategy's current hardcoded behavior; trading_config.json
# only needs to specify values that differ from these.
_DEFAULTS: dict[str, dict[str, Any]] = {
    "newstrading": {"mode": "paper", "run_interval_minutes": 30},
    "wheeltrading": {"mode": "paper", "run_interval_minutes": 30},
    "goldtrading": {"mode": "paper", "run_interval_minutes": 30},
    "bullcallspread": {"mode": "paper", "run_interval_minutes": 30},
    "btctrend": {"mode": "paper", "run_interval_minutes": 5},
}

VALID_INTERVALS = (5, 10, 15, 20, 30, 60)


def _load_raw() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open() as f:
        return json.load(f)


def get_strategy_config(strategy: str) -> dict[str, Any]:
    """Return {"mode": "paper"|"live", "run_interval_minutes": int} for a strategy."""
    if strategy not in _DEFAULTS:
        raise ValueError(f"Unknown strategy: {strategy!r}. Known strategies: {sorted(_DEFAULTS)}")

    defaults = _DEFAULTS[strategy]
    overrides = _load_raw().get(strategy, {})

    mode = overrides.get("mode", defaults["mode"])
    interval = overrides.get("run_interval_minutes", defaults["run_interval_minutes"])

    if mode not in ("paper", "live"):
        raise ValueError(f"{strategy}: mode must be 'paper' or 'live', got {mode!r}")
    if mode == "live" and strategy not in STRATEGIES_WITH_LIVE_PATH:
        raise ValueError(
            f"{strategy}: mode='live' is not available. This strategy has no live-trading "
            f"code path; enabling live execution requires an explicitly-approved, "
            f"approval-gated implementation (see CLAUDE.md). Set mode back to 'paper' in "
            f"trading_config.json."
        )
    if not isinstance(interval, int) or interval not in VALID_INTERVALS:
        raise ValueError(f"{strategy}: run_interval_minutes must be one of {VALID_INTERVALS}, got {interval!r}")

    return {"mode": mode, "run_interval_minutes": interval}
