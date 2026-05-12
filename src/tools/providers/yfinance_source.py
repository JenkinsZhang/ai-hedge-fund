"""yfinance-backed source for prices, statements, and shares.

Forbidden: Ticker.info["marketCap"] and Ticker.info["sharesOutstanding"]
— these return current values and would create lookahead bias in backtests.
"""

from __future__ import annotations

import logging

import yfinance as yf

from src.data.models import Price

logger = logging.getLogger(__name__)


def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """OHLCV bars between start_date and end_date (inclusive)."""
    try:
        df = yf.Ticker(ticker).history(
            start=start_date, end=end_date, auto_adjust=False
        )
    except Exception as exc:
        logger.warning("yfinance.history failed for %s: %s", ticker, exc)
        return []

    if df.empty:
        return []

    out: list[Price] = []
    for ts, row in df.iterrows():
        out.append(
            Price(
                open=float(row["Open"]),
                close=float(row["Close"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                volume=int(row["Volume"]),
                time=ts.strftime("%Y-%m-%d"),
            )
        )
    return out
