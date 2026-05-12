"""Environment-driven configuration for the yfinance provider stack."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    data_provider: str
    alpha_vantage_api_key: str | None
    sec_edgar_user_agent: str | None
    aws_bearer_token: str | None
    cache_dir: Path


def _default_cache_dir() -> Path:
    return Path.home() / ".cache" / "ai-hedge-fund"


def load_config() -> Config:
    """Read env vars and validate. Raises ValueError on hard misconfigurations."""
    provider = os.getenv("DATA_PROVIDER", "financial_datasets").strip().lower()
    av_key = os.getenv("ALPHAVANTAGE_API_KEY") or None
    sec_ua = os.getenv("SEC_EDGAR_USER_AGENT") or None
    bedrock_token = os.getenv("AWS_BEARER_TOKEN_BEDROCK") or None
    cache_override = os.getenv("PROVIDER_CACHE_DIR")
    cache_dir = Path(cache_override) if cache_override else _default_cache_dir()

    if provider == "yfinance":
        if not sec_ua:
            raise ValueError(
                "DATA_PROVIDER=yfinance requires SEC_EDGAR_USER_AGENT env "
                "(format: 'your-name your-email@example.com'). SEC EDGAR "
                "rejects anonymous requests."
            )
        if not av_key:
            logger.warning(
                "ALPHAVANTAGE_API_KEY not set — news will fall back to "
                "yfinance + Bedrock; insider trades will rely on SEC only."
            )
        if not bedrock_token:
            logger.warning(
                "AWS_BEARER_TOKEN_BEDROCK not set — sentiment fallback "
                "will be unavailable."
            )

    return Config(
        data_provider=provider,
        alpha_vantage_api_key=av_key,
        sec_edgar_user_agent=sec_ua,
        aws_bearer_token=bedrock_token,
        cache_dir=cache_dir,
    )


def banner(cfg: Config) -> str:
    """Single-line startup message describing the active provider."""
    if cfg.data_provider != "yfinance":
        return f"Using data provider: {cfg.data_provider}"
    parts = [
        f"alpha_vantage={'enabled' if cfg.alpha_vantage_api_key else 'missing'}",
        f"sec_edgar={'enabled' if cfg.sec_edgar_user_agent else 'missing'}",
        f"bedrock={'enabled' if cfg.aws_bearer_token else 'missing'}",
    ]
    return f"Using data provider: yfinance  ({', '.join(parts)})"
