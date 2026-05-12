from unittest.mock import patch

from src.data.models import Price
from src.tools.providers import derived


def test_market_cap_is_close_times_shares():
    fake_prices = [Price(open=1, high=2, low=1, close=170.5, volume=1, time="2024-06-28")]
    fake_quarters = [
        {"report_period": "2024-03-31", "outstanding_shares": 15_000_000_000},
    ]
    with patch.object(derived, "_fetch_prices_window", return_value=fake_prices), \
         patch.object(derived, "_fetch_pit_quarters", return_value=fake_quarters):
        mc = derived.compute_market_cap_pit("AAPL", end_date="2024-06-30")
    assert mc == 170.5 * 15_000_000_000


def test_market_cap_returns_none_without_shares():
    fake_prices = [Price(open=1, high=2, low=1, close=170.5, volume=1, time="2024-06-28")]
    with patch.object(derived, "_fetch_prices_window", return_value=fake_prices), \
         patch.object(derived, "_fetch_pit_quarters", return_value=[]):
        assert derived.compute_market_cap_pit("AAPL", end_date="2024-06-30") is None


def test_market_cap_returns_none_without_close():
    with patch.object(derived, "_fetch_prices_window", return_value=[]), \
         patch.object(derived, "_fetch_pit_quarters", return_value=[{"outstanding_shares": 1}]):
        assert derived.compute_market_cap_pit("AAPL", end_date="2024-06-30") is None
