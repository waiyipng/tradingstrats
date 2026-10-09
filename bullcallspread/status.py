"""Read-only status used by the dashboard bull call spread panel. No IBKR connection required."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from newstrading.common import load_json
from bullcallspread.state import load_state

RECOMMENDATIONS_DIR = Path(__file__).resolve().parent / "data" / "recommendations"
EXECUTION_REPORTS_DIR = Path(__file__).resolve().parent / "data" / "execution_reports"


def _newest(directory: Path) -> dict[str, Any] | None:
    if not directory.exists():
        return None
    files = list(directory.glob("*.json"))
    return load_json(max(files, key=lambda path: path.stat().st_mtime)) if files else None


def bullcallspread_status() -> dict[str, Any]:
    state = load_state()
    open_positions = [position for position in state.get("open_positions", []) if position["status"] == "open"]
    automated_dir = Path(__file__).resolve().parent / "data" / "automated_runs"
    latest_automated_run = _newest(automated_dir)
    return {
        "latest_recommendation": latest_automated_run or _newest(RECOMMENDATIONS_DIR),
        "latest_execution": _newest(EXECUTION_REPORTS_DIR),
        "open_positions": open_positions,
    }
