from unittest.mock import patch

from src.data.models import CompanyNews
from src.tools.providers import bedrock_sentiment


def _news(title: str) -> CompanyNews:
    return CompanyNews(
        ticker="AAPL", title=title, source="yfinance", date="2024-05-01",
        url="x", author=None, sentiment=None,
    )


def test_annotate_assigns_sentiment_per_title():
    fake_content = '{"items":[{"i":0,"s":"bullish"},{"i":1,"s":"bearish"},{"i":2,"s":"neutral"}]}'

    with patch.object(bedrock_sentiment, "_invoke_haiku", return_value=fake_content):
        news_in = [_news("Apple soars"), _news("Apple plunges"), _news("Apple holds steady")]
        out = bedrock_sentiment.annotate(news_in)

    assert out[0].sentiment == "bullish"
    assert out[1].sentiment == "bearish"
    assert out[2].sentiment == "neutral"


def test_annotate_empty_list_returns_empty():
    assert bedrock_sentiment.annotate([]) == []


def test_annotate_falls_back_to_neutral_on_invoke_error():
    with patch.object(bedrock_sentiment, "_invoke_haiku", side_effect=RuntimeError("boom")):
        out = bedrock_sentiment.annotate([_news("Apple soars")])
    assert out[0].sentiment == "neutral"
