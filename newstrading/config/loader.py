"""Loads the multi-symbol watchlist (ticker -> sector + name aliases) config."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from newstrading.config.environment import load_environment

load_environment()

WATCHLIST_PATH = Path(__file__).resolve().parent / "watchlist.json"


@lru_cache(maxsize=1)
def load_watchlist() -> List[Dict[str, Any]]:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_symbol_entry(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    for entry in load_watchlist():
        if entry["symbol"] == symbol:
            return entry
    raise KeyError(f"{symbol} is not present in config/watchlist.json")


def market_data_symbol(symbol: str) -> str:
    entry = get_symbol_entry(symbol)
    return str(entry.get("market_data_symbol", entry["symbol"]))


def all_symbols() -> List[str]:
    return [entry["symbol"] for entry in load_watchlist()]
