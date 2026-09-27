"""Optional price/trend context (20-day SMA) via yfinance, degrading gracefully if unavailable."""
from __future__ import annotations

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency
    yf = None

from newstrading.models.signal import MarketContext


def get_market_context(symbol: str, lookback_days: int = 30) -> MarketContext:
    if yf is None:
        return MarketContext()
    try:
        data = yf.download(symbol, period=f"{lookback_days}d", progress=False, auto_adjust=True)
        if data.empty or "Close" not in data.columns:
            return MarketContext()
        close = data["Close"]
        if getattr(close, "ndim", 1) == 2:
            # Newer yfinance returns a (Price, Ticker) MultiIndex even for a single symbol.
            close = close.iloc[:, 0]
        close = close.dropna()
        if close.empty:
            return MarketContext()
        price = float(close.iloc[-1])
        sma_20 = float(close.rolling(window=20, min_periods=1).mean().iloc[-1])
        ratio = price / sma_20 if sma_20 else 1.0
        trend = "BULLISH" if ratio > 1.02 else "BEARISH" if ratio < 0.98 else "NEUTRAL"
        return MarketContext(current_price=price, sma_20=sma_20, trend=trend)
    except Exception:
        return MarketContext()
