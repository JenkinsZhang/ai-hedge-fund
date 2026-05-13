"""Shared HTTP utilities: session factory, retry on 429."""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


def make_session(default_headers: dict[str, str] | None = None) -> requests.Session:
    """Build a fresh requests Session with optional default headers.

    Proxy support comes from the standard HTTPS_PROXY / HTTP_PROXY env
    vars, which load_config() ensures are populated. requests honours
    these automatically — no per-session proxies dict needed.
    """
    session = requests.Session()
    if default_headers:
        session.headers.update(default_headers)
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
