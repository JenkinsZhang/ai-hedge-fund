from pathlib import Path

from src.tools.providers import sec_edgar


def test_parse_form4_extracts_apple_sale():
    xml_text = (Path(__file__).parent / "fixtures" / "sec_form4_apple.xml").read_text()
    trades = sec_edgar.parse_form4_xml(
        xml_text, ticker="AAPL", filing_date="2024-04-17"
    )
    assert len(trades) == 1
    t = trades[0]
    assert t.ticker == "AAPL"
    assert t.name == "COOK TIMOTHY D"
    assert t.title == "CEO"
    assert t.is_board_director is True  # the flag means "insider" (director OR officer)
    assert t.transaction_date == "2024-04-15"
    assert t.filing_date == "2024-04-17"
    assert t.transaction_shares == 10000
    assert t.transaction_price_per_share == 170.50
    assert t.transaction_value == 10000 * 170.50
    assert t.shares_owned_after_transaction == 3266000


def test_parse_form4_returns_empty_on_malformed_xml():
    trades = sec_edgar.parse_form4_xml("<not xml", ticker="AAPL", filing_date="2024-04-17")
    assert trades == []
