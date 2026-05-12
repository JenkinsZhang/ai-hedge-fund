from unittest.mock import patch

from src.tools.providers import sec_edgar


def test_resolve_cik_finds_apple():
    fake_payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }
    with patch.object(sec_edgar, "_fetch_company_tickers", return_value=fake_payload):
        assert sec_edgar.resolve_cik("AAPL") == "0000320193"
        assert sec_edgar.resolve_cik("aapl") == "0000320193"


def test_resolve_cik_unknown_returns_none():
    with patch.object(sec_edgar, "_fetch_company_tickers", return_value={}):
        assert sec_edgar.resolve_cik("ZZZZZ") is None


def test_get_filing_dates_maps_report_to_filing():
    fake_submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-Q", "8-K", "10-Q"],
                "filingDate": ["2024-04-30", "2024-01-31", "2024-01-25", "2023-10-30"],
                "reportDate": ["2024-03-31", "2023-12-31", "", "2023-09-30"],
            }
        }
    }
    with patch.object(sec_edgar, "_fetch_submissions", return_value=fake_submissions):
        m = sec_edgar.get_filing_dates("0000320193")

    assert m["2024-03-31"] == "2024-04-30"
    assert m["2023-12-31"] == "2024-01-31"
    assert "" not in m  # 8-K rows without reportDate are skipped


def test_form4_xml_paths_strip_xsl_prefix():
    """Verify XSL-styled view paths are normalized to raw XML paths."""
    fake_submissions = {
        "filings": {
            "recent": {
                "form": ["4", "4", "4"],
                "filingDate": ["2024-04-15", "2024-04-16", "2024-04-17"],
                "accessionNumber": [
                    "0000320193-24-000001",
                    "0000320193-24-000002",
                    "0000320193-24-000003",
                ],
                "primaryDocument": [
                    "xslF345X05/wf-form4_1745234567.xml",  # XSL view — must strip
                    "xslF345X03/wf-form4_1745234568.xml",  # different XSL version
                    "wf-form4_1745234569.xml",              # already raw — leave alone
                ],
            }
        }
    }
    from unittest.mock import patch
    from src.tools.providers import sec_edgar

    with patch.object(sec_edgar, "_fetch_submissions", return_value=fake_submissions):
        paths = sec_edgar._fetch_form4_xml_paths(
            "0000320193", start_date="2024-01-01", end_date="2024-12-31"
        )

    assert len(paths) == 3
    # All three URLs should NOT contain "xsl" segment
    for fd, url in paths:
        assert "xslF345" not in url, f"XSL prefix not stripped: {url}"
        assert url.endswith(".xml")
    # Filenames preserved
    assert paths[0][1].endswith("wf-form4_1745234567.xml")
    assert paths[2][1].endswith("wf-form4_1745234569.xml")
