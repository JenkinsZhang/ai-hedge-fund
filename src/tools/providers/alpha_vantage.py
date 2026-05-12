"""Alpha Vantage client: NEWS_SENTIMENT (primary), INSIDER_TRANSACTIONS (fallback)."""

from __future__ import annotations

import logging
import time

from src.data.models import CompanyNews, InsiderTrade
from src.tools.providers import _config
from src.tools.providers._http import get_with_retry, make_session

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_RATE_LIMIT_SLEEP = 12  # 5 RPM = 12 seconds between calls


def _get_json(params: dict) -> dict | None:
    """GET against AV; return None if config missing or response invalid."""
    cfg = _config.load_config()
    if not cfg.alpha_vantage_api_key:
        return None
    s = make_session()
    time.sleep(_RATE_LIMIT_SLEEP)
    r = get_with_retry(s, _BASE, params={**params, "apikey": cfg.alpha_vantage_api_key})
    if r.status_code != 200:
        logger.warning("AV %s returned %s", params.get("function"), r.status_code)
        return None
    try:
        return r.json()
    except Exception as exc:
        logger.warning("AV JSON parse failed: %s", exc)
        return None


def _is_rate_limited(payload: dict) -> bool:
    return any(k in payload for k in ("Note", "Information"))


def _label_to_sentiment(label: str) -> str:
    label = label.lower()
    if "bullish" in label:
        return "bullish"
    if "bearish" in label:
        return "bearish"
    return "neutral"


def fetch_news(
    ticker: str, start_date: str, end_date: str, limit: int = 100
) -> list[CompanyNews] | None:
    """Return news with sentiment, or None to signal caller should fall back."""
    payload = _get_json({
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "limit": limit,
        "time_from": start_date.replace("-", "") + "T0000",
        "time_to": end_date.replace("-", "") + "T2359",
    })
    if payload is None:
        return None
    if _is_rate_limited(payload):
        logger.warning("AV rate-limited for %s news; fallback advised", ticker)
        return None

    out: list[CompanyNews] = []
    for item in payload.get("feed", []):
        sentiment = "neutral"
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker") == ticker:
                sentiment = _label_to_sentiment(ts.get("ticker_sentiment_label", ""))
                break
        authors = item.get("authors") or []
        out.append(
            CompanyNews(
                ticker=ticker,
                title=item.get("title", ""),
                author=authors[0] if authors else None,
                source=item.get("source", "alpha_vantage"),
                date=item.get("time_published", "")[:8],
                url=item.get("url", ""),
                sentiment=sentiment,
            )
        )
    return out


def fetch_insider_trades(
    ticker: str, start_date: str, end_date: str, limit: int = 1000
) -> list[InsiderTrade] | None:
    """Return insider trades; convention: negative shares for disposals.

    Returns None if AV unreachable or rate-limited.
    """
    payload = _get_json({"function": "INSIDER_TRANSACTIONS", "symbol": ticker})
    if payload is None or _is_rate_limited(payload):
        return None

    out: list[InsiderTrade] = []
    for row in payload.get("data", []):
        tx_date = row.get("transaction_date")
        if not tx_date or not (start_date <= tx_date <= end_date):
            continue
        try:
            shares = float(row.get("shares") or 0)
            price = float(row.get("share_price") or 0)
        except ValueError:
            continue
        is_disposal = row.get("acquisition_or_disposal") == "D"
        signed_shares = -shares if is_disposal else shares
        out.append(
            InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=row.get("executive"),
                title=row.get("executive_title"),
                is_board_director=None,
                transaction_date=tx_date,
                transaction_shares=signed_shares,
                transaction_price_per_share=price,
                transaction_value=signed_shares * price,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=row.get("security_type"),
                filing_date=tx_date,  # AV doesn't expose filing_date separately
            )
        )
    return out[:limit]
