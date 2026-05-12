from unittest.mock import patch

from src.data.models import CompanyNews, InsiderTrade, Price
from src.tools.providers import dispatch


def test_fetch_prices_delegates_to_yfinance(yfinance_env, temp_cache_dir):
    with patch("src.tools.providers.dispatch.yfinance_source.fetch_prices",
               return_value=[Price(open=1, high=1, low=1, close=1, volume=1, time="2024-01-02")]) as m:
        out = dispatch.fetch_prices("AAPL", "2024-01-01", "2024-01-05")
    m.assert_called_once_with("AAPL", "2024-01-01", "2024-01-05")
    assert len(out) == 1


def test_fetch_company_news_uses_av_first_then_falls_back(yfinance_env, temp_cache_dir):
    fake_yf_titles = [
        CompanyNews(ticker="AAPL", title="t1", source="yf", date="2024-05-01",
                    url="x", sentiment=None),
    ]

    with patch("src.tools.providers.dispatch.alpha_vantage.fetch_news", return_value=None), \
         patch("src.tools.providers.dispatch.yfinance_source.fetch_news_titles",
               return_value=fake_yf_titles), \
         patch("src.tools.providers.dispatch.bedrock_sentiment.annotate",
               side_effect=lambda news: [n.model_copy(update={"sentiment": "neutral"}) for n in news]) as bd:
        out = dispatch.fetch_company_news("AAPL", "2024-05-31", "2024-05-01", limit=10)

    bd.assert_called_once()
    assert out[0].sentiment == "neutral"


def test_fetch_insider_trades_falls_back_to_av(yfinance_env, temp_cache_dir):
    av_trades = [InsiderTrade(ticker="AAPL", filing_date="2024-04-15", name="x",
                              issuer=None, title=None, is_board_director=None,
                              transaction_date="2024-04-15", transaction_shares=-100,
                              transaction_price_per_share=170.0,
                              transaction_value=-17000.0,
                              shares_owned_before_transaction=None,
                              shares_owned_after_transaction=None,
                              security_title="Common")]
    with patch("src.tools.providers.dispatch.sec_edgar.fetch_form4_trades", return_value=[]), \
         patch("src.tools.providers.dispatch.alpha_vantage.fetch_insider_trades",
               return_value=av_trades) as av:
        out = dispatch.fetch_insider_trades("AAPL", end_date="2024-06-30",
                                            start_date="2024-01-01", limit=10)
    av.assert_called_once()
    assert len(out) == 1
