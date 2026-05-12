"""Derived layer: TTM composer + PIT market_cap + 41 self-computed ratios.

Single contract:
- compose_ttm(quarters) -> dict | None
- compute_market_cap_pit(...)
- compute_financial_metrics(...)

All callers expect None on insufficient/invalid data; never raises.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Income statement and cash flow flows: sum across 4 quarters
FLOW_FIELDS: set[str] = {
    "revenue", "gross_profit", "operating_income", "operating_expense",
    "net_income", "ebit", "ebitda", "interest_expense",
    "free_cash_flow", "capital_expenditure", "depreciation_and_amortization",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "research_and_development", "earnings_per_share",
}

# Balance sheet stocks: take latest period
STOCK_FIELDS: set[str] = {
    "total_assets", "current_assets", "cash_and_equivalents",
    "total_liabilities", "current_liabilities", "total_debt",
    "shareholders_equity", "outstanding_shares",
    "goodwill_and_intangible_assets",
}


def compose_ttm(quarters: list[dict]) -> dict | None:
    """Build a TTM record from at least 4 newest-first quarterly dicts.

    Returns None if fewer than 4 quarters available.
    """
    if not quarters or len(quarters) < 4:
        return None
    latest = quarters[0]
    last4 = quarters[:4]

    out: dict[str, Any] = {
        "ticker": latest.get("ticker"),
        "report_period": latest["report_period"],
        "period": "ttm",
        "currency": latest.get("currency", "USD"),
    }

    for field in FLOW_FIELDS:
        vals = [q.get(field) for q in last4]
        present = [v for v in vals if v is not None]
        out[field] = sum(present) if present else None

    for field in STOCK_FIELDS:
        out[field] = latest.get(field)

    return out


def safe_div(num, den):
    """Divide; return None on zero/None operand or NaN/inf result."""
    if num is None or den in (None, 0):
        return None
    try:
        result = num / den
    except ZeroDivisionError:
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _growth(curr, prev):
    if curr is None or prev in (None, 0):
        return None
    return curr / prev - 1


def compute_metrics(ttm: dict, *, prev_ttm: dict | None, market_cap: float | None,
                    ticker: str, currency: str = "USD"):
    """Build a FinancialMetrics from TTM, previous TTM, and PIT market cap.

    All 41 fields are filled where possible; missing dependencies → None
    (partial fill).
    """
    from src.data.models import FinancialMetrics

    rev = ttm.get("revenue")
    ni = ttm.get("net_income")
    ebit = ttm.get("ebit")
    ebitda = ttm.get("ebitda")
    op_inc = ttm.get("operating_income")
    gross = ttm.get("gross_profit")
    fcf = ttm.get("free_cash_flow")
    ie = ttm.get("interest_expense")
    eps = ttm.get("earnings_per_share")

    assets = ttm.get("total_assets")
    ca = ttm.get("current_assets")
    cash = ttm.get("cash_and_equivalents")
    cl = ttm.get("current_liabilities")
    debt = ttm.get("total_debt")
    equity = ttm.get("shareholders_equity")
    shares = ttm.get("outstanding_shares")

    # Enterprise value: market_cap + debt - cash
    ev = None
    if market_cap is not None:
        ev = market_cap + (debt or 0) - (cash or 0)

    # ROIC: NOPAT / invested_capital
    tax_rate = 0.21
    nopat = ebit * (1 - tax_rate) if ebit is not None else None
    invested_capital = None
    if debt is not None and equity is not None:
        invested_capital = debt + equity - (cash or 0)
    roic = safe_div(nopat, invested_capital)

    # Growth fields (4Q back)
    prev = prev_ttm or {}
    earnings_growth = _growth(ni, prev.get("net_income"))

    return FinancialMetrics(
        ticker=ticker,
        report_period=ttm.get("report_period"),
        period=ttm.get("period", "ttm"),
        currency=currency,
        market_cap=market_cap,
        enterprise_value=ev,
        # Valuation
        price_to_earnings_ratio=safe_div(market_cap, ni),
        price_to_book_ratio=safe_div(market_cap, equity),
        price_to_sales_ratio=safe_div(market_cap, rev),
        enterprise_value_to_ebitda_ratio=safe_div(ev, ebitda),
        enterprise_value_to_revenue_ratio=safe_div(ev, rev),
        free_cash_flow_yield=safe_div(fcf, market_cap),
        peg_ratio=safe_div(safe_div(market_cap, ni), earnings_growth),
        # Profitability
        gross_margin=safe_div(gross, rev),
        operating_margin=safe_div(op_inc, rev),
        net_margin=safe_div(ni, rev),
        return_on_equity=safe_div(ni, equity),
        return_on_assets=safe_div(ni, assets),
        return_on_invested_capital=roic,
        # Efficiency
        asset_turnover=safe_div(rev, assets),
        inventory_turnover=None,
        receivables_turnover=None,
        days_sales_outstanding=None,
        operating_cycle=None,
        working_capital_turnover=None,
        # Liquidity
        current_ratio=safe_div(ca, cl),
        quick_ratio=safe_div(ca, cl) if ca is not None else None,
        cash_ratio=safe_div(cash, cl),
        operating_cash_flow_ratio=safe_div(fcf, cl),
        # Leverage
        debt_to_equity=safe_div(debt, equity),
        debt_to_assets=safe_div(debt, assets),
        interest_coverage=safe_div(ebit, abs(ie) if ie else None),
        # Growth
        revenue_growth=_growth(rev, prev.get("revenue")),
        earnings_growth=earnings_growth,
        book_value_growth=_growth(equity, prev.get("shareholders_equity")),
        earnings_per_share_growth=_growth(eps, prev.get("earnings_per_share")),
        free_cash_flow_growth=_growth(fcf, prev.get("free_cash_flow")),
        operating_income_growth=_growth(op_inc, prev.get("operating_income")),
        ebitda_growth=_growth(ebitda, prev.get("ebitda")),
        # Per-share
        payout_ratio=None,
        earnings_per_share=eps,
        book_value_per_share=safe_div(equity, shares),
        free_cash_flow_per_share=safe_div(fcf, shares),
    )


def filter_pit(
    quarters: list[dict],
    filing_dates: dict[str, str],
    *,
    decision_date: str,
) -> list[dict]:
    """Keep only quarters whose filing_date <= decision_date.

    Drops periods missing from filing_dates (per spec: never assume future).
    """
    kept: list[dict] = []
    for q in quarters:
        rp = q.get("report_period")
        if not rp:
            continue
        fd = filing_dates.get(rp)
        if fd is None:
            continue
        if fd > decision_date:
            continue
        kept.append(q)
    return kept
