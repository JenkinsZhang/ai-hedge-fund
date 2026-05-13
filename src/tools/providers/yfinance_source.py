"""yfinance-backed source for prices, statements, and shares.

Forbidden: Ticker.info["marketCap"] and Ticker.info["sharesOutstanding"]
— these return current values and would create lookahead bias in backtests.
"""

from __future__ import annotations

import logging
import threading
import time

import requests
import yfinance as yf

from src.data.models import Price

logger = logging.getLogger(__name__)

_YF_LAST_CALL_TS = 0.0
_YF_LOCK = threading.Lock()
_YF_MIN_INTERVAL = 0.6  # seconds between yfinance calls
_YF_MAX_RETRIES = 3
_YF_RETRY_BACKOFF = 5  # base seconds for 429 backoff

# Cached requests Session pre-configured with proxy (if any) for yfinance use.
_YF_SESSION: requests.Session | None = None


def _yf_session() -> requests.Session:
    """Build (and cache) a requests Session with proxy from Config.

    yfinance 0.2.x accepts `session=` on Ticker(); requests will use the
    session's proxies dict for every HTTP call. Falls back to direct connect
    if no proxy is configured.
    """
    global _YF_SESSION
    if _YF_SESSION is not None:
        return _YF_SESSION

    from src.tools.providers._config import load_config
    s = requests.Session()
    proxy = load_config().proxy
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
        logger.info("yfinance routing through proxy: %s", proxy)
    _YF_SESSION = s
    return s


def _yf_throttle():
    """Block until at least _YF_MIN_INTERVAL has passed since the last call."""
    global _YF_LAST_CALL_TS
    with _YF_LOCK:
        now = time.time()
        wait = _YF_MIN_INTERVAL - (now - _YF_LAST_CALL_TS)
        if wait > 0:
            time.sleep(wait)
        _YF_LAST_CALL_TS = time.time()


def _yf_call_with_retry(callable_):
    """Run a yfinance callable, retrying on 'Too Many Requests' errors."""
    for attempt in range(_YF_MAX_RETRIES + 1):
        _yf_throttle()
        try:
            return callable_()
        except Exception as exc:
            msg = str(exc).lower()
            is_rate_limited = "too many requests" in msg or "rate limit" in msg or "429" in msg
            if is_rate_limited and attempt < _YF_MAX_RETRIES:
                delay = _YF_RETRY_BACKOFF * (attempt + 1)
                logger.warning(
                    "yfinance rate-limited; retrying in %ds (attempt %d/%d)",
                    delay, attempt + 1, _YF_MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            raise


def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """OHLCV bars between start_date and end_date (inclusive)."""
    try:
        df = _yf_call_with_retry(
            lambda: yf.Ticker(ticker, session=_yf_session()).history(
                start=start_date, end=end_date, auto_adjust=False
            )
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


# Mapping of canonical line-item names to the multiple labels yfinance
# may use across schema revisions. First match wins.
LINE_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income",),
    "operating_expense": ("Operating Expense",),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "ebit": ("EBIT", "Operating Income"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "interest_expense": ("Interest Expense",),
    "earnings_per_share": ("Basic EPS", "Diluted EPS"),
    "research_and_development": ("Research And Development",),
    "depreciation_and_amortization": ("Depreciation And Amortization",),
    "capital_expenditure": ("Capital Expenditure",),
    "free_cash_flow": ("Free Cash Flow",),
    "dividends_and_other_cash_distributions": ("Cash Dividends Paid",),
    "issuance_or_purchase_of_equity_shares": ("Net Common Stock Issuance",),
    "total_assets": ("Total Assets",),
    "current_assets": ("Current Assets",),
    "cash_and_equivalents": ("Cash And Cash Equivalents", "Cash"),
    "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liabilities"),
    "current_liabilities": ("Current Liabilities",),
    "total_debt": ("Total Debt",),
    "shareholders_equity": ("Stockholders Equity", "Common Stock Equity"),
    "goodwill_and_intangible_assets": ("Goodwill And Other Intangible Assets",),
    "outstanding_shares": ("Ordinary Shares Number", "Share Issued"),
}

# Capex in yfinance is stored as a negative number (a use of cash).
# Buffett-style ratios expect positive magnitude.
_CAPEX_KEYS = {"capital_expenditure"}


def _lookup(df, candidates: tuple[str, ...], col):
    """Find the first candidate row that exists and has a non-NaN value at col."""
    for name in candidates:
        if name in df.index:
            val = df.at[name, col]
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if fval != fval:  # NaN
                continue
            return fval
    return None


def fetch_quarterly_statements(ticker: str) -> list[dict]:
    """Combine three quarterly statements into one list of period dicts.

    Each entry has 'ticker', 'report_period' (YYYY-MM-DD), 'period'='quarterly',
    and the canonical line-item keys from LINE_ITEM_CANDIDATES (or absent if
    not found in this period).
    """
    try:
        def _fetch():
            t = yf.Ticker(ticker, session=_yf_session())
            return t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
        income, balance, cashflow = _yf_call_with_retry(_fetch)
    except Exception as exc:
        logger.warning("yfinance quarterly statements failed for %s: %s", ticker, exc)
        return []

    if income is None or income.empty:
        return []

    # Union of all reported periods, newest first
    cols = sorted(
        set(income.columns) | set(balance.columns) | set(cashflow.columns),
        reverse=True,
    )

    out: list[dict] = []
    for col in cols:
        period_dt = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
        record: dict = {
            "ticker": ticker,
            "report_period": period_dt,
            "period": "quarterly",
            "currency": "USD",
        }
        for canonical, candidates in LINE_ITEM_CANDIDATES.items():
            for source_df in (income, balance, cashflow):
                if col not in source_df.columns:
                    continue
                val = _lookup(source_df, candidates, col)
                if val is not None:
                    if canonical in _CAPEX_KEYS:
                        val = abs(val)
                    record[canonical] = val
                    break
        out.append(record)
    return out


def fetch_news_titles(ticker: str, start_date: str, end_date: str, limit: int = 50):
    """Best-effort: pull recent news titles via yfinance (no sentiment).

    Returns list of CompanyNews with sentiment=None. Caller annotates downstream.
    """
    from src.data.models import CompanyNews

    try:
        items = _yf_call_with_retry(
            lambda: yf.Ticker(ticker, session=_yf_session()).news
        ) or []
    except Exception as exc:
        logger.warning("yfinance news failed for %s: %s", ticker, exc)
        return []

    out: list[CompanyNews] = []
    for it in items[:limit]:
        title = it.get("title") or it.get("content", {}).get("title", "")
        link = it.get("link") or it.get("content", {}).get("canonicalUrl", {}).get("url", "")
        publisher = it.get("publisher") or it.get("content", {}).get("provider", {}).get("displayName", "yfinance")
        ts = it.get("providerPublishTime")
        date = ""
        if isinstance(ts, (int, float)):
            from datetime import datetime, timezone
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if not title:
            continue
        if start_date and date and date < start_date:
            continue
        if end_date and date and date > end_date:
            continue
        out.append(CompanyNews(
            ticker=ticker, title=title, author=None, source=publisher,
            date=date, url=link, sentiment=None,
        ))
    return out
