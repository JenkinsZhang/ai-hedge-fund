from src.tools.providers import derived


def test_safe_div_handles_zero_and_none():
    assert derived.safe_div(10, 2) == 5.0
    assert derived.safe_div(10, 0) is None
    assert derived.safe_div(None, 5) is None
    assert derived.safe_div(10, None) is None


def _ttm_curr():
    return {
        "ticker": "AAPL", "report_period": "2026-03-31", "period": "ttm", "currency": "USD",
        "revenue": 400, "gross_profit": 160, "operating_income": 80, "net_income": 60,
        "ebit": 80, "ebitda": 100, "interest_expense": 10,
        "free_cash_flow": 50, "capital_expenditure": 20,
        "earnings_per_share": 0.60,
        "total_assets": 1000, "current_assets": 300, "cash_and_equivalents": 50,
        "total_liabilities": 600, "current_liabilities": 150, "total_debt": 200,
        "shareholders_equity": 400, "outstanding_shares": 100,
    }


def _ttm_prev():
    base = _ttm_curr()
    base["revenue"] = 320
    base["net_income"] = 48
    base["free_cash_flow"] = 40
    base["ebitda"] = 80
    base["operating_income"] = 64
    base["shareholders_equity"] = 350
    return base


def test_compute_ratios_basic():
    fm = derived.compute_metrics(
        _ttm_curr(), prev_ttm=_ttm_prev(), market_cap=12000, ticker="AAPL",
    )
    assert fm.gross_margin == 0.4
    assert fm.operating_margin == 0.2
    assert fm.net_margin == 0.15
    assert fm.return_on_equity == 60 / 400
    assert fm.return_on_assets == 60 / 1000
    assert fm.current_ratio == 2.0
    assert fm.debt_to_equity == 0.5
    assert fm.interest_coverage == 8.0
    assert fm.price_to_earnings_ratio == 12000 / 60
    assert fm.price_to_book_ratio == 12000 / 400
    assert fm.price_to_sales_ratio == 12000 / 400


def test_growth_uses_4_quarters_back():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=None, ticker="AAPL")
    assert fm.revenue_growth == (400 / 320) - 1
    assert fm.earnings_growth == (60 / 48) - 1
    assert fm.free_cash_flow_growth == (50 / 40) - 1
    assert fm.ebitda_growth == (100 / 80) - 1


def test_partial_fill_when_market_cap_missing():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=None, ticker="AAPL")
    assert fm.market_cap is None
    assert fm.price_to_earnings_ratio is None
    assert fm.gross_margin == 0.4
    assert fm.return_on_equity == 60 / 400


def test_roic_formula():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=12000, ticker="AAPL")
    # nopat = ebit*(1-0.21) = 80*0.79 = 63.2
    # invested_capital = total_debt + equity - cash = 200 + 400 - 50 = 550
    assert fm.return_on_invested_capital == 63.2 / 550
