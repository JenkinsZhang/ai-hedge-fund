from unittest.mock import patch

from src.tools.providers import alpha_vantage


def _av_news_payload():
    return {
        "feed": [
            {
                "title": "Apple beats earnings",
                "url": "https://example.com/a",
                "time_published": "20240501T120000",
                "source": "Reuters",
                "authors": ["Jane Doe"],
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_label": "Somewhat-Bullish"}
                ],
            },
            {
                "title": "Apple cuts forecast",
                "url": "https://example.com/b",
                "time_published": "20240502T120000",
                "source": "Bloomberg",
                "authors": [],
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_label": "Bearish"}
                ],
            },
        ]
    }


def test_fetch_news_normalizes_av_payload(yfinance_env):
    with patch.object(alpha_vantage, "_get_json", return_value=_av_news_payload()):
        news = alpha_vantage.fetch_news("AAPL", "2024-04-01", "2024-05-31", limit=10)

    assert len(news) == 2
    assert news[0].title == "Apple beats earnings"
    assert news[0].sentiment == "bullish"
    assert news[0].source == "Reuters"
    assert news[0].author == "Jane Doe"
    assert news[1].sentiment == "bearish"


def test_fetch_news_returns_none_on_rate_limit(yfinance_env):
    with patch.object(alpha_vantage, "_get_json", return_value={"Note": "Thank you for using Alpha Vantage"}):
        news = alpha_vantage.fetch_news("AAPL", "2024-04-01", "2024-05-31", limit=10)
    assert news is None


def test_fetch_insider_normalizes(yfinance_env):
    payload = {
        "data": [
            {
                "transaction_date": "2024-04-15",
                "ticker": "AAPL",
                "executive": "COOK TIMOTHY D",
                "executive_title": "CEO",
                "security_type": "Common Stock",
                "acquisition_or_disposal": "D",
                "shares": "10000",
                "share_price": "170.50",
            }
        ]
    }
    with patch.object(alpha_vantage, "_get_json", return_value=payload):
        trades = alpha_vantage.fetch_insider_trades("AAPL", "2024-01-01", "2024-12-31", limit=10)

    assert len(trades) == 1
    t = trades[0]
    assert t.name == "COOK TIMOTHY D"
    assert t.transaction_shares == -10000  # 'D' = disposal = negative
    assert t.transaction_price_per_share == 170.50
