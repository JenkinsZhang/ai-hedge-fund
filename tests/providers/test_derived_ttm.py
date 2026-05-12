from src.tools.providers import derived


def _quarters():
    """Return 5 quarters newest-first; flow values 100/90/85/80/75."""
    return [
        {"report_period": "2024-03-31", "revenue": 100, "net_income": 20,
         "total_assets": 1000, "shareholders_equity": 400, "outstanding_shares": 100,
         "free_cash_flow": 18, "ebitda": 30, "ebit": 25, "interest_expense": 2,
         "operating_income": 25, "gross_profit": 40,
         "current_assets": 300, "current_liabilities": 150, "total_liabilities": 600,
         "cash_and_equivalents": 50, "total_debt": 200, "depreciation_and_amortization": 8,
         "capital_expenditure": 5, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.20,
         "research_and_development": 5, "operating_expense": 15,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-12-31", "revenue": 90,  "net_income": 15,
         "total_assets": 900,  "shareholders_equity": 380, "outstanding_shares": 100,
         "free_cash_flow": 14, "ebitda": 22, "ebit": 18, "interest_expense": 2,
         "operating_income": 20, "gross_profit": 35,
         "current_assets": 280, "current_liabilities": 140, "total_liabilities": 540,
         "cash_and_equivalents": 45, "total_debt": 210, "depreciation_and_amortization": 7,
         "capital_expenditure": 4, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.15,
         "research_and_development": 4, "operating_expense": 14,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-09-30", "revenue": 85,  "net_income": 14,
         "total_assets": 850, "shareholders_equity": 360, "outstanding_shares": 100,
         "free_cash_flow": 12, "ebitda": 20, "ebit": 17, "interest_expense": 2,
         "operating_income": 19, "gross_profit": 33,
         "current_assets": 270, "current_liabilities": 135, "total_liabilities": 510,
         "cash_and_equivalents": 40, "total_debt": 220, "depreciation_and_amortization": 7,
         "capital_expenditure": 4, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.14,
         "research_and_development": 4, "operating_expense": 13,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-06-30", "revenue": 80,  "net_income": 12,
         "total_assets": 800, "shareholders_equity": 340, "outstanding_shares": 100,
         "free_cash_flow": 10, "ebitda": 18, "ebit": 15, "interest_expense": 2,
         "operating_income": 17, "gross_profit": 30,
         "current_assets": 260, "current_liabilities": 130, "total_liabilities": 480,
         "cash_and_equivalents": 35, "total_debt": 230, "depreciation_and_amortization": 6,
         "capital_expenditure": 3, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.12,
         "research_and_development": 3, "operating_expense": 12,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-03-31", "revenue": 75,  "net_income": 10,
         "total_assets": 750, "shareholders_equity": 320, "outstanding_shares": 100,
         "free_cash_flow": 8, "ebitda": 16, "ebit": 13, "interest_expense": 2,
         "operating_income": 15, "gross_profit": 28,
         "current_assets": 250, "current_liabilities": 125, "total_liabilities": 450,
         "cash_and_equivalents": 30, "total_debt": 240, "depreciation_and_amortization": 6,
         "capital_expenditure": 3, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.10,
         "research_and_development": 3, "operating_expense": 11,
         "goodwill_and_intangible_assets": 50},
    ]


def test_compose_ttm_sums_flow_fields():
    ttm = derived.compose_ttm(_quarters()[:4])
    assert ttm["revenue"] == 100 + 90 + 85 + 80
    assert ttm["net_income"] == 20 + 15 + 14 + 12
    assert ttm["free_cash_flow"] == 18 + 14 + 12 + 10


def test_compose_ttm_uses_latest_for_stock_fields():
    ttm = derived.compose_ttm(_quarters()[:4])
    assert ttm["total_assets"] == 1000
    assert ttm["shareholders_equity"] == 400
    assert ttm["outstanding_shares"] == 100


def test_compose_ttm_returns_none_with_fewer_than_4_quarters():
    assert derived.compose_ttm(_quarters()[:3]) is None
