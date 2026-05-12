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
