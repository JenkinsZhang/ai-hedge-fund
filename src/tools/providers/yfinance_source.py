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
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        balance = t.quarterly_balance_sheet
        cashflow = t.quarterly_cashflow
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
