"""Dispatch layer: hard-coded fallback chains for the 6 public entries."""

from __future__ import annotations

import logging

from src.data.models import (CompanyNews, FinancialMetrics, InsiderTrade,
                              LineItem, Price)
from src.tools.providers import (alpha_vantage, bedrock_sentiment, derived,
                                  sec_edgar, yfinance_source)
from src.tools.providers._cache import Cache
from src.tools.providers._config import banner, load_config

logger = logging.getLogger(__name__)
_BANNER_PRINTED = False
_CACHE: Cache | None = None


def _emit_banner_once() -> None:
    global _BANNER_PRINTED
    if _BANNER_PRINTED:
        return
    cfg = load_config()
    logger.info(banner(cfg))
    print(banner(cfg))
    _BANNER_PRINTED = True


def _cache() -> Cache:
    global _CACHE
    if _CACHE is None:
        cfg = load_config()
        _CACHE = Cache(cfg.cache_dir / "providers.db")
    return _CACHE


def _cached(key: str, ttl: int, fn):
    """Look up key in SQLite cache; on miss, call fn(), store, return."""
    c = _cache()
    hit = c.get(key)
    if hit is not None:
        return hit
    val = fn()
    if val is not None:
        c.set(key, val, ttl)
    return val


# -------------------- public dispatch functions --------------------

def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    _emit_banner_once()
    key = f"yfinance:prices:{ticker}:{start_date}:{end_date}:day:v1"
    return _cached(key, 0, lambda: yfinance_source.fetch_prices(ticker, start_date, end_date)) or []


def fetch_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str,
    limit: int,
) -> list[LineItem]:
    _emit_banner_once()
    items_key = ",".join(sorted(line_items))
    key = f"yfinance:line_items:{ticker}:{items_key}:{end_date}:{period}:{limit}:v1"

    def _build():
        from src.tools.providers.yfinance_source import LINE_ITEM_CANDIDATES
        quarters = derived._fetch_pit_quarters(ticker, end_date)
        # Pre-populate every key the agent asked for + every canonical key we
        # know, so that LineItem(**payload).<field> never raises AttributeError
        # even when yfinance didn't expose the value.
        baseline_keys = set(LINE_ITEM_CANDIDATES) | set(line_items)
        out: list[LineItem] = []
        for q in quarters[:limit]:
            payload = {k: None for k in baseline_keys}
            payload.update(q)
            try:
                out.append(LineItem(**payload))
            except Exception as exc:
                logger.warning("LineItem validation failed for %s/%s: %s", ticker, q.get("report_period"), exc)
        return out

    return _cached(key, 7 * 86400, _build) or []


def fetch_financial_metrics(
    ticker: str, end_date: str, period: str, limit: int
) -> list[FinancialMetrics]:
    _emit_banner_once()
    key = f"derived:financial_metrics:{ticker}::{end_date}:{period}:{limit}:v1"

    def _build():
        quarters = derived._fetch_pit_quarters(ticker, end_date)
        if len(quarters) < 4:
            return []
        ttm_curr = derived.compose_ttm(quarters)
        ttm_prev = derived.compose_ttm(quarters[4:8]) if len(quarters) >= 8 else None
        market_cap = derived.compute_market_cap_pit(ticker, end_date)
        fm = derived.compute_metrics(
            ttm_curr, prev_ttm=ttm_prev, market_cap=market_cap, ticker=ticker,
        )
        return [fm][:limit]

    return _cached(key, 7 * 86400, _build) or []


def fetch_market_cap(ticker: str, end_date: str) -> float | None:
    _emit_banner_once()
    key = f"derived:market_cap_pit:{ticker}::{end_date}::v1"
    return _cached(key, 7 * 86400,
                   lambda: derived.compute_market_cap_pit(ticker, end_date))


def fetch_company_news(
    ticker: str, end_date: str, start_date: str | None, limit: int
) -> list[CompanyNews]:
    _emit_banner_once()
    sd = start_date or "1970-01-01"
    key = f"news:{ticker}:{sd}:{end_date}:{limit}:v1"

    def _build():
        # Primary: Alpha Vantage with sentiment
        out = alpha_vantage.fetch_news(ticker, sd, end_date, limit)
        if out is not None:
            return out
        # Fallback: yfinance titles + Bedrock sentiment
        titles = yfinance_source.fetch_news_titles(ticker, sd, end_date, limit)
        if not titles:
            return []
        return bedrock_sentiment.annotate(titles)

    return _cached(key, 86400, _build) or []


def fetch_insider_trades(
    ticker: str, end_date: str, start_date: str | None, limit: int
) -> list[InsiderTrade]:
    _emit_banner_once()
    sd = start_date or "1970-01-01"
    key = f"insider:{ticker}:{sd}:{end_date}:{limit}:v1"

    def _build():
        try:
            sec_trades = sec_edgar.fetch_form4_trades(ticker, sd, end_date, limit)
        except Exception as exc:
            logger.warning("SEC Form 4 fetch failed for %s: %s", ticker, exc)
            sec_trades = []
        if sec_trades:
            return sec_trades
        av_trades = alpha_vantage.fetch_insider_trades(ticker, sd, end_date, limit)
        return av_trades or []

    return _cached(key, 86400, _build) or []
