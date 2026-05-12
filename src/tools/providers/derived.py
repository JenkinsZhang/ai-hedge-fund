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
