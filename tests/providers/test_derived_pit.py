from src.tools.providers import derived


def test_filter_pit_drops_periods_with_late_filing():
    quarters = [
        {"report_period": "2024-03-31"},
        {"report_period": "2023-12-31"},
        {"report_period": "2023-09-30"},
    ]
    filing_dates = {
        "2024-03-31": "2024-04-30",  # filed AFTER decision date
        "2023-12-31": "2024-01-31",  # filed before
        "2023-09-30": "2023-10-30",  # filed before
    }
    kept = derived.filter_pit(quarters, filing_dates, decision_date="2024-04-15")
    assert len(kept) == 2
    assert kept[0]["report_period"] == "2023-12-31"


def test_filter_pit_estimates_filing_date_when_missing():
    """Foreign issuers (ADRs) often have no quarterly filing_date in SEC.
    Fall back to report_period + 60 days as a conservative estimate."""
    quarters = [{"report_period": "2024-03-31"}, {"report_period": "2023-12-31"}]
    filing_dates: dict[str, str] = {}  # both missing — ADR scenario

    # decision_date well after both estimated filing windows: keep both
    kept = derived.filter_pit(quarters, filing_dates, decision_date="2024-09-30")
    assert len(kept) == 2

    # decision_date before 2024-03-31 + 60d (= 2024-05-30): drop newer one only
    kept = derived.filter_pit(quarters, filing_dates, decision_date="2024-04-01")
    assert len(kept) == 1
    assert kept[0]["report_period"] == "2023-12-31"


def test_filter_pit_skips_unparseable_report_period():
    quarters = [{"report_period": "garbage"}]
    kept = derived.filter_pit(quarters, {}, decision_date="2024-06-30")
    assert kept == []


def test_filter_pit_handles_empty_inputs():
    assert derived.filter_pit([], {}, decision_date="2024-01-01") == []
