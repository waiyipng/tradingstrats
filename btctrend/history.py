"""Daily BTC-USD bars from yfinance (UTC days). Signals only use completed bars.

yfinance sometimes publishes today's partial bar before yesterday's completed one;
completed days missing at the end are filled from Coinbase's public daily candles.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import yfinance as yf

COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
# Reuse a download for this long within the same UTC day, so frequent stop-check
# cycles don't hammer yfinance.
CACHE_SECONDS = 15 * 60
_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}


def _fill_recent_from_coinbase(bars: pd.DataFrame, today) -> pd.DataFrame:
    first_missing = bars.index[-1].date() + timedelta(days=1)
    if first_missing >= today:
        return bars
    try:
        response = requests.get(
            COINBASE_CANDLES_URL,
            params={"granularity": 86400, "start": first_missing.isoformat(), "end": today.isoformat()},
            timeout=8,
            headers={"User-Agent": "tradingstrats-btctrend"},
        )
        response.raise_for_status()
        rows = response.json()  # [time, low, high, open, close, volume], newest first
    except (requests.RequestException, ValueError):
        return bars  # staleness is caught downstream by the bar-age guard
    extra = pd.DataFrame(
        [{"open": row[3], "high": row[2], "low": row[1], "close": row[4]} for row in rows],
        index=pd.to_datetime([row[0] for row in rows], unit="s").normalize(),
    )
    extra = extra[(extra.index.date >= first_missing) & (extra.index.date < today)]
    return pd.concat([bars, extra]).sort_index() if not extra.empty else bars


def fetch_daily_bars(symbol: str, start: str | None = None, lookback_days: int | None = None) -> pd.DataFrame:
    """Return open/high/low/close indexed by UTC date, excluding today's partial bar."""
    today = datetime.now(timezone.utc).date()
    key = (symbol, start, lookback_days, today)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    if start is None:
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=lookback_days or 450)).strftime("%Y-%m-%d")
    try:
        raw = yf.download(symbol, start=start, progress=False, auto_adjust=False)
    except Exception as exc:  # yfinance surfaces network failures as assorted exception types
        raise RuntimeError(f"daily history download failed for {symbol}: {exc}") from exc
    if raw is None or raw.empty:
        raise RuntimeError(f"no daily history returned for {symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(symbol, axis=1, level="Ticker")
    bars = raw.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    bars.index = pd.to_datetime(bars.index).tz_localize(None).normalize()
    bars = bars[bars.index.date < today]
    if symbol == "BTC-USD":
        bars = _fill_recent_from_coinbase(bars, today)
    _cache.clear()
    _cache[key] = (time.monotonic(), bars)
    return bars


def bar_age_days(bars: pd.DataFrame) -> int:
    """Days between the newest completed bar and yesterday (0 = fully current)."""
    return (datetime.now(timezone.utc).date() - timedelta(days=1) - bars.index[-1].date()).days
