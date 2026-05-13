"""Shared HTTP utilities: session factory, retry on 429."""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


def make_session(default_headers: dict[str, str] | None = None) -> requests.Session:
    """Build a fresh requests Session with optional default headers.

    Honours the `proxy` field on Config (set via YFINANCE_PROXY / HTTPS_PROXY /
    HTTP_PROXY env). Lazy-imported to avoid a circular import at module load.
    """
    session = requests.Session()
    if default_headers:
        session.headers.update(default_headers)
    try:
        from src.tools.providers._config import load_config
        proxy = load_config().proxy
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
    except Exception:
        # If config can't load (e.g. during early bootstrap), proceed without proxy.
        pass
    return session


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 3,
    backoff_base: int = 5,
) -> requests.Response:
    """GET with linear backoff on 429.

    Returns the response in all cases (success, 4xx, 5xx, exhausted retries).
    Only 429 triggers retry; other failures bubble up to caller for handling.
    """
    for attempt in range(max_retries + 1):
        response = session.get(url, params=params, timeout=20)
        if response.status_code != 429 or attempt >= max_retries:
            return response
        delay = backoff_base + 5 * attempt
        logger.warning(
            "HTTP 429 from %s — retrying in %ds (attempt %d/%d)",
            url, delay, attempt + 1, max_retries,
        )
        time.sleep(delay)
    return response
