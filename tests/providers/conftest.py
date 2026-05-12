from pathlib import Path

import pytest


@pytest.fixture()
def temp_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PROVIDER_CACHE_DIR at a per-test tmp directory."""
    monkeypatch.setenv("PROVIDER_CACHE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def yfinance_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the minimum env vars required for the yfinance provider stack."""
    monkeypatch.setenv("DATA_PROVIDER", "yfinance")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "test-runner test@example.com")
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-av-key")


@pytest.fixture(autouse=True)
def reset_dispatch_cache():
    """Reset dispatch module's cache singleton between tests."""
    try:
        from src.tools.providers import dispatch as _dispatch
    except ImportError:
        yield
        return
    _dispatch._CACHE = None
    _dispatch._BANNER_PRINTED = False
    yield
    _dispatch._CACHE = None
