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


def _txt(root, path: str) -> str | None:
    node = root.find(path)
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _flt(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_form4_xml(xml_text: str, ticker: str, filing_date: str) -> list:
    """Parse a Form 4 ownershipDocument into InsiderTrade rows.

    Returns [] on malformed XML — never raises.
    """
    from xml.etree import ElementTree as ET

    from src.data.models import InsiderTrade

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("Form 4 XML parse failed for %s/%s: %s", ticker, filing_date, exc)
        return []

    issuer = _txt(root, ".//issuer/issuerName")
    owner_name = _txt(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    is_director = _txt(root, ".//reportingOwner/reportingOwnerRelationship/isDirector") == "1"
    is_officer = _txt(root, ".//reportingOwner/reportingOwnerRelationship/isOfficer") == "1"
    title = _txt(root, ".//reportingOwner/reportingOwnerRelationship/officerTitle")

    trades: list = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        tx_date = _txt(tx, ".//transactionDate/value")
        code = _txt(tx, ".//transactionCoding/transactionCode")
        shares = _flt(_txt(tx, ".//transactionShares/value"))
        price = _flt(_txt(tx, ".//transactionPricePerShare/value"))
        owned_after = _flt(_txt(tx, ".//sharesOwnedFollowingTransaction/value"))
        sec_title = _txt(tx, ".//securityTitle/value")

        value = (shares * price) if (shares is not None and price is not None) else None

        trades.append(
            InsiderTrade(
                ticker=ticker,
                issuer=issuer,
                name=owner_name,
                title=title,
                is_board_director=is_director or is_officer,  # FD's flag means "insider"
                transaction_date=tx_date,
                transaction_shares=shares,
                transaction_price_per_share=price,
                transaction_value=value,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=owned_after,
                security_title=sec_title,
                filing_date=filing_date,
            )
        )
    return trades


def _fetch_form4_xml_paths(cik10: str, start_date: str, end_date: str) -> list[tuple[str, str]]:
    """Return list of (filing_date, xml_url) for Form 4 filings in window."""
    sub = _fetch_submissions(cik10)
    recent = sub.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    fdates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    out: list[tuple[str, str]] = []
    for form, fd, acc, doc in zip(forms, fdates, accessions, primary_docs):
        if form not in ("4", "4/A"):
            continue
        if not (start_date <= fd <= end_date):
            continue
        acc_clean = acc.replace("-", "")
        # SEC's primaryDocument field for Form 4 sometimes points to an XSL-styled
        # view (e.g., "xslF345X05/wf-form4_xxx.xml") which returns HTML. Strip the
        # xsl* directory prefix so we hit the raw XML at the accession root.
        doc_clean = doc
        if "/" in doc_clean:
            parts = doc_clean.split("/")
            if parts[0].startswith("xsl"):
                doc_clean = parts[-1]
        url = f"{_BASE_FILES}/Archives/edgar/data/{int(cik10)}/{acc_clean}/{doc_clean}"
        out.append((fd, url))
    return out


def fetch_form4_trades(ticker: str, start_date: str, end_date: str, limit: int = 1000):
    """Resolve CIK, list Form 4 filings in window, parse each."""
    cik = resolve_cik(ticker)
    if cik is None:
        logger.warning("SEC CIK lookup failed for %s", ticker)
        return []
    paths = _fetch_form4_xml_paths(cik, start_date, end_date)
    s = _session()
    out = []
    for fd, url in paths[:limit]:
        time.sleep(_RATE_LIMIT_SLEEP)
        r = get_with_retry(s, url)
        if r.status_code != 200:
            continue
        out.extend(parse_form4_xml(r.text, ticker=ticker, filing_date=fd))
    return out
