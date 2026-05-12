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


def test_filter_pit_drops_periods_with_no_filing_date():
    quarters = [{"report_period": "2024-03-31"}, {"report_period": "2023-12-31"}]
    filing_dates = {"2023-12-31": "2024-01-31"}  # 2024-Q1 missing
    kept = derived.filter_pit(quarters, filing_dates, decision_date="2024-06-30")
    assert len(kept) == 1
    assert kept[0]["report_period"] == "2023-12-31"


def test_filter_pit_handles_empty_inputs():
    assert derived.filter_pit([], {}, decision_date="2024-01-01") == []
