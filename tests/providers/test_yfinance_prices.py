from unittest.mock import patch

import pandas as pd

from src.tools.providers import yfinance_source


def _fake_history_df():
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [1_000_000, 1_500_000],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )


def test_fetch_prices_maps_yfinance_columns():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = _fake_history_df()

        prices = yfinance_source.fetch_prices("AAPL", "2024-01-01", "2024-01-05")

    assert len(prices) == 2
    assert prices[0].open == 100.0
    assert prices[0].close == 101.0
    assert prices[0].time == "2024-01-02"
    assert prices[1].volume == 1_500_000


def test_fetch_prices_returns_empty_on_empty_df():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        prices = yfinance_source.fetch_prices("ZZZZZ", "2024-01-01", "2024-01-05")
    assert prices == []
