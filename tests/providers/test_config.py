import os
import pytest

from src.tools.providers import _config


def test_config_defaults_to_financial_datasets(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    cfg = _config.load_config()
    assert cfg.data_provider == "financial_datasets"


def test_config_yfinance_requires_sec_user_agent(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yfinance")
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="SEC_EDGAR_USER_AGENT"):
        _config.load_config()


def test_config_yfinance_warns_when_keys_missing(monkeypatch, caplog):
    monkeypatch.setenv("DATA_PROVIDER", "yfinance")
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "x x@x.com")
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    with caplog.at_level("WARNING"):
        cfg = _config.load_config()

    assert cfg.alpha_vantage_api_key is None
    assert any("ALPHAVANTAGE_API_KEY" in r.message for r in caplog.records)


def test_config_cache_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PROVIDER_CACHE_DIR", str(tmp_path))
    cfg = _config.load_config()
    assert cfg.cache_dir == tmp_path
