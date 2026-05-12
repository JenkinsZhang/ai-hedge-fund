"""Live end-to-end smoke test for yfinance provider stack.

Run with: pytest tests/integration/test_yfinance_smoke.py -m live

Requires:
- Internet connectivity
- SEC_EDGAR_USER_AGENT set in .env
- Optional: ALPHAVANTAGE_API_KEY, AWS_BEARER_TOKEN_BEDROCK
"""

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def force_yfinance_provider(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yfinance")
    if not os.getenv("SEC_EDGAR_USER_AGENT"):
        pytest.skip("SEC_EDGAR_USER_AGENT not set")


def test_get_prices_returns_data():
    from src.tools.api import get_prices
    prices = get_prices("AAPL", "2024-06-01", "2024-06-30")
    assert len(prices) > 5
    assert all(p.close > 0 for p in prices)


def test_get_financial_metrics_returns_at_least_partial():
    from src.tools.api import get_financial_metrics
    metrics = get_financial_metrics("AAPL", "2024-06-30", period="ttm", limit=1)
    assert len(metrics) == 1
    assert metrics[0].gross_margin is not None


def test_get_market_cap_pit_returns_value():
    from src.tools.api import get_market_cap
    mc = get_market_cap("AAPL", "2024-06-30")
    assert mc is not None
    assert 1e12 < mc < 1e13
