"""Routing contract: api.py honours DATA_PROVIDER without breaking FD mode."""

from src.tools import api


def test_fd_mode_default_does_not_route_to_dispatch(monkeypatch):
    """In FD mode, api.get_prices must NOT call dispatch.fetch_prices."""
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    called = {"dispatch": False}

    def boom(*a, **k):
        called["dispatch"] = True
        raise AssertionError("dispatch should not be called in FD mode")

    monkeypatch.setattr("src.tools.providers.dispatch.fetch_prices", boom, raising=False)

    # Stub the FD HTTP layer so the test doesn't hit the network.
    class FakeResp:
        status_code = 500
        def json(self):
            return {}

    monkeypatch.setattr(api, "_make_api_request",
                        lambda *a, **kw: FakeResp())
    result = api.get_prices("AAPL", "2024-01-01", "2024-01-05")
    assert result == []
    assert called["dispatch"] is False


def test_yfinance_mode_routes_to_dispatch(monkeypatch, yfinance_env):
    seen = {}

    def fake_dispatch_fetch_prices(ticker, start, end):
        seen["call"] = (ticker, start, end)
        return []

    monkeypatch.setattr("src.tools.providers.dispatch.fetch_prices",
                        fake_dispatch_fetch_prices, raising=False)
    api.get_prices("AAPL", "2024-01-01", "2024-01-05")
    assert seen["call"] == ("AAPL", "2024-01-01", "2024-01-05")
