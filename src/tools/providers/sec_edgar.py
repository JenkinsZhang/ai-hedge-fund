"""SEC EDGAR client: CIK resolver, submissions JSON, Form 4 parser.

Requires SEC_EDGAR_USER_AGENT env (validated at config load).
"""

from __future__ import annotations

import logging
import time

from src.tools.providers import _config
from src.tools.providers._http import get_with_retry, make_session

logger = logging.getLogger(__name__)

_BASE_DATA = "https://data.sec.gov"
_BASE_FILES = "https://www.sec.gov"
_RATE_LIMIT_SLEEP = 0.11  # ~9 RPS, safely under SEC's 10 RPS cap


def _session():
    cfg = _config.load_config()
    return make_session({
        "User-Agent": cfg.sec_edgar_user_agent or "anonymous test@example.com",
        "Accept": "application/json",
    })


def _fetch_company_tickers() -> dict:
    s = _session()
    time.sleep(_RATE_LIMIT_SLEEP)
    r = get_with_retry(s, f"{_BASE_FILES}/files/company_tickers.json")
    if r.status_code != 200:
        logger.warning("SEC company_tickers fetch failed: %s", r.status_code)
        return {}
    return r.json()


def resolve_cik(ticker: str) -> str | None:
    """Return zero-padded 10-digit CIK string, or None."""
    payload = _fetch_company_tickers()
    target = ticker.upper().strip()
    for entry in payload.values():
        if entry.get("ticker", "").upper() == target:
            return str(entry["cik_str"]).zfill(10)
    return None


def _fetch_submissions(cik10: str) -> dict:
    s = _session()
    time.sleep(_RATE_LIMIT_SLEEP)
    r = get_with_retry(s, f"{_BASE_DATA}/submissions/CIK{cik10}.json")
    if r.status_code != 200:
        logger.warning("SEC submissions for %s failed: %s", cik10, r.status_code)
        return {}
    return r.json()


def get_filing_dates(cik10: str) -> dict[str, str]:
    """Return {report_period: filing_date} for 10-K and 10-Q filings."""
    sub = _fetch_submissions(cik10)
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    out: dict[str, str] = {}
    for form, fd, rd in zip(forms, filing_dates, report_dates):
        if form not in ("10-Q", "10-K", "20-F", "10-K/A", "10-Q/A"):
            continue
        if not rd:
            continue
        # Keep the earliest filing_date for a given report_period
        if rd not in out or fd < out[rd]:
            out[rd] = fd
    return out
