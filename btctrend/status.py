"""Read-only status used by the dashboard BTC trend panel. No IBKR connection required."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from newstrading.common import load_json
from btctrend.backtest import REPORT_PATH
from btctrend.state import load_state, ytd_realized_pnl

AUTOMATED_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"
MANUAL_DIR = Path(__file__).resolve().parent / "data" / "manual_runs"


def _newest(*directories: Path) -> dict[str, Any] | None:
    files = [path for directory in directories if directory.exists() for path in directory.glob("*.json")]
    return load_json(max(files, key=lambda path: path.stat().st_mtime)) if files else None


def btctrend_status() -> dict[str, Any]:
    state = load_state()
    backtest = load_json(REPORT_PATH) if REPORT_PATH.exists() else None
    return {
        "latest_run": _newest(AUTOMATED_DIR, MANUAL_DIR),
        "position": {key: state[key] for key in ("btc_qty", "avg_cost", "held_exposure", "target_qty", "target_set_at", "realized_pnl", "peak_close", "stop_locked", "entry_price", "profit_taken")},
        "recent_fills": state.get("fills", [])[-10:],
        "ytd_realized_pnl": ytd_realized_pnl(state),
        "backtest": {key: backtest[key] for key in ("generated_at", "data", "assumptions", "results")} if backtest else None,
    }
