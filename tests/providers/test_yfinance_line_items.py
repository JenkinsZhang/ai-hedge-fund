from unittest.mock import patch

import pandas as pd

from src.tools.providers import yfinance_source


def _fake_quarterly_income():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Total Revenue": 100, "Net Income": 20, "Operating Income": 25},
            cols[1]: {"Total Revenue": 90,  "Net Income": 15, "Operating Income": 20},
            cols[2]: {"Total Revenue": 85,  "Net Income": 14, "Operating Income": 19},
            cols[3]: {"Total Revenue": 80,  "Net Income": 12, "Operating Income": 17},
        }
    )


def _fake_quarterly_balance():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Total Assets": 1000, "Stockholders Equity": 400, "Total Debt": 200, "Ordinary Shares Number": 100},
            cols[1]: {"Total Assets": 900,  "Stockholders Equity": 380, "Total Debt": 210, "Ordinary Shares Number": 100},
            cols[2]: {"Total Assets": 850,  "Stockholders Equity": 360, "Total Debt": 220, "Ordinary Shares Number": 100},
            cols[3]: {"Total Assets": 800,  "Stockholders Equity": 340, "Total Debt": 230, "Ordinary Shares Number": 100},
        }
    )


def _fake_quarterly_cashflow():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Free Cash Flow": 18, "Capital Expenditure": -5, "Depreciation And Amortization": 8},
            cols[1]: {"Free Cash Flow": 14, "Capital Expenditure": -4, "Depreciation And Amortization": 7},
            cols[2]: {"Free Cash Flow": 12, "Capital Expenditure": -4, "Depreciation And Amortization": 7},
            cols[3]: {"Free Cash Flow": 10, "Capital Expenditure": -3, "Depreciation And Amortization": 6},
        }
    )


def test_fetch_quarterly_statements_returns_dicts_per_period():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        t = mock_ticker.return_value
        t.quarterly_income_stmt = _fake_quarterly_income()
        t.quarterly_balance_sheet = _fake_quarterly_balance()
        t.quarterly_cashflow = _fake_quarterly_cashflow()

        periods = yfinance_source.fetch_quarterly_statements("AAPL")

    assert len(periods) == 4
    # Sorted newest first
    assert periods[0]["report_period"] == "2024-03-31"
    assert periods[0]["revenue"] == 100
    assert periods[0]["net_income"] == 20
    assert periods[0]["total_assets"] == 1000
    assert periods[0]["free_cash_flow"] == 18
    # capex stored as positive magnitude
    assert periods[0]["capital_expenditure"] == 5


def test_fetch_quarterly_statements_handles_missing_field():
    income = _fake_quarterly_income()
    income.loc["Operating Income"] = float("nan")
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        t = mock_ticker.return_value
        t.quarterly_income_stmt = income
        t.quarterly_balance_sheet = _fake_quarterly_balance()
        t.quarterly_cashflow = _fake_quarterly_cashflow()

        periods = yfinance_source.fetch_quarterly_statements("AAPL")

    assert periods[0].get("operating_income") is None
