# yfinance Data Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `DATA_PROVIDER=yfinance` mode to `src/tools/api.py` that delegates to a free-source stack (yfinance + Alpha Vantage + SEC EDGAR + Bedrock Haiku) with strict point-in-time enforcement, while preserving the default `financial_datasets` behaviour byte-for-byte.

**Architecture:** Create `src/tools/providers/` containing a thin Protocol (`DataProvider`), per-source modules (`yfinance_source`, `alpha_vantage`, `sec_edgar`, `bedrock_sentiment`), a `derived` layer (TTM composer + PIT market_cap + 41 self-computed ratios), shared `_http`/`_cache`/`_config` helpers, and a `dispatch.py` with hard-coded fallback chains. `api.py`'s 6 functions get a 4-line top-of-body env switch; agents and Pydantic models stay unchanged.

**Tech Stack:** Python 3.11, yfinance 0.2.50+, requests (existing), SQLite (stdlib), pickle (stdlib), pytest, langchain-aws (already added in earlier work).

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/tools/providers/__init__.py` | Re-export `dispatch` for upstream import |
| `src/tools/providers/_config.py` | Read & validate env vars; expose `Config` dataclass; emit startup banner |
| `src/tools/providers/_http.py` | `requests.Session` factory with retry-on-429, rate-limit decorator |
| `src/tools/providers/_cache.py` | SQLite-backed cache (`get(key)` / `set(key, value, ttl)`) |
| `src/tools/providers/yfinance_source.py` | OHLCV, three-statement reports, quarterly shares |
| `src/tools/providers/alpha_vantage.py` | NEWS_SENTIMENT (primary), INSIDER_TRANSACTIONS (fallback) |
| `src/tools/providers/sec_edgar.py` | CIK resolver, submissions JSON, Form 4 XML parser, filing_date lookup |
| `src/tools/providers/bedrock_sentiment.py` | Haiku 4.5 batch sentiment annotator |
| `src/tools/providers/derived.py` | TTM composer, PIT market_cap, 41 FinancialMetrics ratios |
| `src/tools/providers/dispatch.py` | 6 dispatcher functions with hard-coded fallback chains |
| `tests/providers/__init__.py` | (empty) |
| `tests/providers/conftest.py` | Shared fixtures (mock SQLite path, fake env) |
| `tests/providers/test_dispatch_routing.py` | api.py FD-mode never imports providers |
| `tests/providers/test_cache.py` | SQLite hit/miss/TTL |
| `tests/providers/test_derived_ttm.py` | TTM 4-quarter sum correctness |
| `tests/providers/test_derived_pit.py` | future filing_date drops the period |
| `tests/providers/test_derived_metrics.py` | 41 fields formula correctness |
| `tests/providers/test_sec_form4_parser.py` | XML round-trip from fixture |
| `tests/providers/fixtures/sec_form4_apple.xml` | Real SEC Form 4 sample |
| `tests/integration/__init__.py` | (empty) |
| `tests/integration/test_yfinance_smoke.py` | Live end-to-end smoke (`@pytest.mark.live`) |

### Modified files

| Path | Change |
|---|---|
| `src/tools/api.py` | Add 4-line env-switch branch at top of each of the 6 functions |
| `pyproject.toml` | Add `yfinance = "^0.2.50"` |
| `.env.example` | Add 4 env vars (DATA_PROVIDER, ALPHAVANTAGE_API_KEY, SEC_EDGAR_USER_AGENT, PROVIDER_CACHE_DIR) |

### Untouched (verified)

- `src/data/models.py` — Pydantic models stay as-is
- `src/data/cache.py` — FD-mode in-memory cache stays
- `src/agents/*.py`, `src/utils/*.py`, `src/llm/*.py` (Bedrock provider was added in earlier work)
- `app/backend/*`, `app/frontend/*`
- `v2/*`

---

## Task 0: Add yfinance dependency and env vars

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 0.1: Add yfinance to dependencies**

Open `pyproject.toml` and add this line in the `[tool.poetry.dependencies]` block, immediately after `langchain-aws = "^0.2.35"`:

```toml
yfinance = "^0.2.50"
```

- [ ] **Step 0.2: Update .env.example**

Append to the bottom of `.env.example`:

```bash

# --- Data Provider ---
# Set to 'yfinance' to use the free-source stack (yfinance + Alpha Vantage +
# SEC EDGAR + Bedrock). Leave unset or set to 'financial_datasets' to keep
# using the paid Financial Datasets API (default).
DATA_PROVIDER=financial_datasets

# Alpha Vantage — used as primary news sentiment + insider trades fallback
# when DATA_PROVIDER=yfinance. Free key: https://www.alphavantage.co/support/#api-key
ALPHAVANTAGE_API_KEY=

# SEC EDGAR User-Agent (REQUIRED when DATA_PROVIDER=yfinance).
# SEC rejects anonymous requests. Format: "your-name your-email@example.com"
SEC_EDGAR_USER_AGENT=

# Optional: override cache directory. Default: ~/.cache/ai-hedge-fund/
PROVIDER_CACHE_DIR=
```

- [ ] **Step 0.3: Refresh poetry lock (skip if user runs install themselves)**

Run: `poetry lock`
Expected: `poetry.lock` updates with yfinance and its transitive deps.

If poetry is unavailable, skip this step — the user will run install manually.

- [ ] **Step 0.4: Commit**

```bash
git add pyproject.toml .env.example poetry.lock
git commit -m "chore: add yfinance dependency and DATA_PROVIDER env vars

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: Bootstrap providers package + Config

**Files:**
- Create: `src/tools/providers/__init__.py`
- Create: `src/tools/providers/_config.py`
- Create: `tests/providers/__init__.py`
- Create: `tests/providers/conftest.py`
- Test: `tests/providers/test_config.py`

- [ ] **Step 1.1: Create empty package init**

Create `src/tools/providers/__init__.py` with content:

```python
"""yfinance free-source data provider stack.

Public surface is `dispatch.fetch_*` functions. All other modules are internal.
"""
```

Create `tests/providers/__init__.py` (empty).

- [ ] **Step 1.2: Create test conftest**

Create `tests/providers/conftest.py`:

```python
import os
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
```

- [ ] **Step 1.3: Write the failing test for Config**

Create `tests/providers/test_config.py`:

```python
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
```

- [ ] **Step 1.4: Run test to verify it fails**

Run: `pytest tests/providers/test_config.py -v`
Expected: All 4 tests FAIL with `ModuleNotFoundError: No module named 'src.tools.providers._config'`.

- [ ] **Step 1.5: Implement _config.py**

Create `src/tools/providers/_config.py`:

```python
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
```

- [ ] **Step 1.6: Run test to verify it passes**

Run: `pytest tests/providers/test_config.py -v`
Expected: 4 PASS.

- [ ] **Step 1.7: Commit**

```bash
git add src/tools/providers/__init__.py src/tools/providers/_config.py tests/providers/
git commit -m "feat(providers): add Config loader with env validation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: SQLite cache layer

**Files:**
- Create: `src/tools/providers/_cache.py`
- Test: `tests/providers/test_cache.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/providers/test_cache.py`:

```python
import time

import pytest

from src.tools.providers._cache import Cache


def test_cache_set_and_get(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("key1", [1, 2, 3], ttl_seconds=60)
    assert cache.get("key1") == [1, 2, 3]


def test_cache_miss_returns_none(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    assert cache.get("missing") is None


def test_cache_respects_ttl(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("expiring", "v", ttl_seconds=0)  # 0 means forever in our schema
    assert cache.get("expiring") == "v"


def test_cache_expired_entry_returns_none(temp_cache_dir, monkeypatch):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("short", "v", ttl_seconds=1)
    fake_now = time.time() + 100
    monkeypatch.setattr(time, "time", lambda: fake_now)
    assert cache.get("short") is None


def test_cache_overwrite(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("k", "v1", ttl_seconds=60)
    cache.set("k", "v2", ttl_seconds=60)
    assert cache.get("k") == "v2"


def test_cache_creates_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    cache = Cache(nested / "test.db")
    cache.set("k", 1, ttl_seconds=60)
    assert cache.get("k") == 1
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `pytest tests/providers/test_cache.py -v`
Expected: All FAIL with `ModuleNotFoundError`.

- [ ] **Step 2.3: Implement _cache.py**

Create `src/tools/providers/_cache.py`:

```python
"""SQLite-backed cache for provider responses.

Single-table design. Values are pickled. ttl_seconds=0 means never expire.
"""

from __future__ import annotations

import pickle
import sqlite3
import time
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       BLOB NOT NULL,
    fetched_at  INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetched_at ON cache(fetched_at);
"""


class Cache:
    """Thread-safe SQLite cache.

    `ttl_seconds=0` means the entry never expires.
    """

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, fetched_at, ttl_seconds FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value_blob, fetched_at, ttl_seconds = row
        if ttl_seconds > 0 and time.time() - fetched_at > ttl_seconds:
            return None
        return pickle.loads(value_blob)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        blob = pickle.dumps(value)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, fetched_at, ttl_seconds) "
            "VALUES (?, ?, ?, ?)",
            (key, blob, int(time.time()), ttl_seconds),
        )

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_cache.py -v`
Expected: 6 PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/tools/providers/_cache.py tests/providers/test_cache.py
git commit -m "feat(providers): add SQLite cache layer with TTL support

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Shared HTTP helper

**Files:**
- Create: `src/tools/providers/_http.py`
- Test: `tests/providers/test_http.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/providers/test_http.py`:

```python
from unittest.mock import Mock, patch

import pytest

from src.tools.providers._http import get_with_retry


def test_get_with_retry_success_first_try():
    mock_session = Mock()
    mock_response = Mock(status_code=200)
    mock_session.get.return_value = mock_response

    response = get_with_retry(mock_session, "https://example.com/api")

    assert response.status_code == 200
    assert mock_session.get.call_count == 1


def test_get_with_retry_handles_429_then_success(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.side_effect = [Mock(status_code=429), Mock(status_code=200)]

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 200
    assert mock_session.get.call_count == 2


def test_get_with_retry_returns_final_429_after_max_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.return_value = Mock(status_code=429)

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 429
    assert mock_session.get.call_count == 3  # initial + 2 retries


def test_get_with_retry_returns_500_immediately(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    mock_session = Mock()
    mock_session.get.return_value = Mock(status_code=500)

    response = get_with_retry(mock_session, "https://example.com/api", max_retries=2)

    assert response.status_code == 500
    assert mock_session.get.call_count == 1  # no retry on 5xx
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `pytest tests/providers/test_http.py -v`
Expected: All FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement _http.py**

Create `src/tools/providers/_http.py`:

```python
"""Shared HTTP utilities: session factory, retry on 429."""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)


def make_session(default_headers: dict[str, str] | None = None) -> requests.Session:
    """Build a fresh requests Session with optional default headers."""
    session = requests.Session()
    if default_headers:
        session.headers.update(default_headers)
    return session


def get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = 3,
    backoff_base: int = 5,
) -> requests.Response:
    """GET with linear backoff on 429.

    Returns the response in all cases (success, 4xx, 5xx, exhausted retries).
    Only 429 triggers retry; other failures bubble up to caller for handling.
    """
    for attempt in range(max_retries + 1):
        response = session.get(url, params=params, timeout=20)
        if response.status_code != 429 or attempt >= max_retries:
            return response
        delay = backoff_base + 5 * attempt
        logger.warning(
            "HTTP 429 from %s — retrying in %ds (attempt %d/%d)",
            url, delay, attempt + 1, max_retries,
        )
        time.sleep(delay)
    return response  # unreachable, but mypy-friendly
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_http.py -v`
Expected: 4 PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/tools/providers/_http.py tests/providers/test_http.py
git commit -m "feat(providers): add HTTP helper with 429 retry

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: yfinance source — prices

**Files:**
- Create: `src/tools/providers/yfinance_source.py` (initial)
- Test: `tests/providers/test_yfinance_prices.py`

- [ ] **Step 4.1: Write the failing test**

Create `tests/providers/test_yfinance_prices.py`:

```python
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.tools.providers import yfinance_source


def _fake_history_df():
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.5],
            "Close": [101.0, 102.5],
            "Volume": [1_000_000, 1_500_000],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )


def test_fetch_prices_maps_yfinance_columns():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = _fake_history_df()

        prices = yfinance_source.fetch_prices("AAPL", "2024-01-01", "2024-01-05")

    assert len(prices) == 2
    assert prices[0].open == 100.0
    assert prices[0].close == 101.0
    assert prices[0].time == "2024-01-02"
    assert prices[1].volume == 1_500_000


def test_fetch_prices_returns_empty_on_empty_df():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        prices = yfinance_source.fetch_prices("ZZZZZ", "2024-01-01", "2024-01-05")
    assert prices == []
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `pytest tests/providers/test_yfinance_prices.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement initial yfinance_source.py with fetch_prices**

Create `src/tools/providers/yfinance_source.py`:

```python
"""yfinance-backed source for prices, statements, and shares.

Forbidden: Ticker.info["marketCap"] and Ticker.info["sharesOutstanding"]
— these return current values and would create lookahead bias in backtests.
"""

from __future__ import annotations

import logging

import yfinance as yf

from src.data.models import Price

logger = logging.getLogger(__name__)


def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """OHLCV bars between start_date and end_date (inclusive)."""
    try:
        df = yf.Ticker(ticker).history(
            start=start_date, end=end_date, auto_adjust=False
        )
    except Exception as exc:
        logger.warning("yfinance.history failed for %s: %s", ticker, exc)
        return []

    if df.empty:
        return []

    out: list[Price] = []
    for ts, row in df.iterrows():
        out.append(
            Price(
                open=float(row["Open"]),
                close=float(row["Close"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                volume=int(row["Volume"]),
                time=ts.strftime("%Y-%m-%d"),
            )
        )
    return out
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_yfinance_prices.py -v`
Expected: 2 PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/tools/providers/yfinance_source.py tests/providers/test_yfinance_prices.py
git commit -m "feat(providers): add yfinance prices fetcher

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: yfinance source — line items mapping

**Files:**
- Modify: `src/tools/providers/yfinance_source.py`
- Test: `tests/providers/test_yfinance_line_items.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/providers/test_yfinance_line_items.py`:

```python
from unittest.mock import patch

import pandas as pd
import pytest

from src.tools.providers import yfinance_source


def _fake_quarterly_income():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Total Revenue": 100, "Net Income": 20, "Operating Income": 25},
            cols[1]: {"Total Revenue": 90,  "Net Income": 15, "Operating Income": 20},
            cols[2]: {"Total Revenue": 85,  "Net Income": 14, "Operating Income": 19},
            cols[3]: {"Total Revenue": 80,  "Net Income": 12, "Operating Income": 17},
        }
    )


def _fake_quarterly_balance():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Total Assets": 1000, "Stockholders Equity": 400, "Total Debt": 200, "Ordinary Shares Number": 100},
            cols[1]: {"Total Assets": 900,  "Stockholders Equity": 380, "Total Debt": 210, "Ordinary Shares Number": 100},
            cols[2]: {"Total Assets": 850,  "Stockholders Equity": 360, "Total Debt": 220, "Ordinary Shares Number": 100},
            cols[3]: {"Total Assets": 800,  "Stockholders Equity": 340, "Total Debt": 230, "Ordinary Shares Number": 100},
        }
    )


def _fake_quarterly_cashflow():
    cols = pd.to_datetime(["2024-03-31", "2023-12-31", "2023-09-30", "2023-06-30"])
    return pd.DataFrame(
        {
            cols[0]: {"Free Cash Flow": 18, "Capital Expenditure": -5, "Depreciation And Amortization": 8},
            cols[1]: {"Free Cash Flow": 14, "Capital Expenditure": -4, "Depreciation And Amortization": 7},
            cols[2]: {"Free Cash Flow": 12, "Capital Expenditure": -4, "Depreciation And Amortization": 7},
            cols[3]: {"Free Cash Flow": 10, "Capital Expenditure": -3, "Depreciation And Amortization": 6},
        }
    )


def test_fetch_quarterly_statements_returns_dicts_per_period():
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        t = mock_ticker.return_value
        t.quarterly_income_stmt = _fake_quarterly_income()
        t.quarterly_balance_sheet = _fake_quarterly_balance()
        t.quarterly_cashflow = _fake_quarterly_cashflow()

        periods = yfinance_source.fetch_quarterly_statements("AAPL")

    assert len(periods) == 4
    # Sorted newest first
    assert periods[0]["report_period"] == "2024-03-31"
    assert periods[0]["revenue"] == 100
    assert periods[0]["net_income"] == 20
    assert periods[0]["total_assets"] == 1000
    assert periods[0]["free_cash_flow"] == 18
    # capex stored as positive magnitude
    assert periods[0]["capital_expenditure"] == 5


def test_fetch_quarterly_statements_handles_missing_field():
    income = _fake_quarterly_income()
    income.loc["Operating Income"] = float("nan")
    with patch.object(yfinance_source.yf, "Ticker") as mock_ticker:
        t = mock_ticker.return_value
        t.quarterly_income_stmt = income
        t.quarterly_balance_sheet = _fake_quarterly_balance()
        t.quarterly_cashflow = _fake_quarterly_cashflow()

        periods = yfinance_source.fetch_quarterly_statements("AAPL")

    assert periods[0].get("operating_income") is None
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `pytest tests/providers/test_yfinance_line_items.py -v`
Expected: FAIL — `fetch_quarterly_statements` not defined.

- [ ] **Step 5.3: Implement fetch_quarterly_statements**

Append to `src/tools/providers/yfinance_source.py`:

```python


# Mapping of canonical line-item names to the multiple labels yfinance
# may use across schema revisions. First match wins.
LINE_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income",),
    "operating_expense": ("Operating Expense",),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "ebit": ("EBIT", "Operating Income"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "interest_expense": ("Interest Expense",),
    "earnings_per_share": ("Basic EPS", "Diluted EPS"),
    "research_and_development": ("Research And Development",),
    "depreciation_and_amortization": ("Depreciation And Amortization",),
    "capital_expenditure": ("Capital Expenditure",),
    "free_cash_flow": ("Free Cash Flow",),
    "dividends_and_other_cash_distributions": ("Cash Dividends Paid",),
    "issuance_or_purchase_of_equity_shares": ("Net Common Stock Issuance",),
    "total_assets": ("Total Assets",),
    "current_assets": ("Current Assets",),
    "cash_and_equivalents": ("Cash And Cash Equivalents", "Cash"),
    "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liabilities"),
    "current_liabilities": ("Current Liabilities",),
    "total_debt": ("Total Debt",),
    "shareholders_equity": ("Stockholders Equity", "Common Stock Equity"),
    "goodwill_and_intangible_assets": ("Goodwill And Other Intangible Assets",),
    "outstanding_shares": ("Ordinary Shares Number", "Share Issued"),
}

# Capex in yfinance is stored as a negative number (a use of cash).
# Buffett-style ratios expect positive magnitude.
_CAPEX_KEYS = {"capital_expenditure"}


def _lookup(df, candidates: tuple[str, ...], col):
    """Find the first candidate row that exists and has a non-NaN value at col."""
    for name in candidates:
        if name in df.index:
            val = df.at[name, col]
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if fval != fval:  # NaN
                continue
            return fval
    return None


def fetch_quarterly_statements(ticker: str) -> list[dict]:
    """Combine three quarterly statements into one list of period dicts.

    Each entry has 'ticker', 'report_period' (YYYY-MM-DD), 'period'='quarterly',
    and the canonical line-item keys from LINE_ITEM_CANDIDATES (or absent if
    not found in this period).
    """
    try:
        t = yf.Ticker(ticker)
        income = t.quarterly_income_stmt
        balance = t.quarterly_balance_sheet
        cashflow = t.quarterly_cashflow
    except Exception as exc:
        logger.warning("yfinance quarterly statements failed for %s: %s", ticker, exc)
        return []

    if income is None or income.empty:
        return []

    # Union of all reported periods, newest first
    cols = sorted(
        set(income.columns) | set(balance.columns) | set(cashflow.columns),
        reverse=True,
    )

    out: list[dict] = []
    for col in cols:
        period_dt = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
        record: dict = {
            "ticker": ticker,
            "report_period": period_dt,
            "period": "quarterly",
            "currency": "USD",
        }
        for canonical, candidates in LINE_ITEM_CANDIDATES.items():
            for source_df in (income, balance, cashflow):
                if col not in source_df.columns:
                    continue
                val = _lookup(source_df, candidates, col)
                if val is not None:
                    if canonical in _CAPEX_KEYS:
                        val = abs(val)
                    record[canonical] = val
                    break
        out.append(record)
    return out
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_yfinance_line_items.py -v`
Expected: 2 PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/tools/providers/yfinance_source.py tests/providers/test_yfinance_line_items.py
git commit -m "feat(providers): add yfinance quarterly statements mapper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: SEC EDGAR — CIK resolver and filing dates

**Files:**
- Create: `src/tools/providers/sec_edgar.py`
- Test: `tests/providers/test_sec_edgar_basics.py`

- [ ] **Step 6.1: Write the failing test**

Create `tests/providers/test_sec_edgar_basics.py`:

```python
from unittest.mock import Mock, patch

import pytest

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


def test_get_filing_dates_maps_report_to_filing(monkeypatch):
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
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `pytest tests/providers/test_sec_edgar_basics.py -v`
Expected: FAIL — module missing.

- [ ] **Step 6.3: Implement sec_edgar.py (CIK + filing dates only)**

Create `src/tools/providers/sec_edgar.py`:

```python
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
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_sec_edgar_basics.py -v`
Expected: 3 PASS.

- [ ] **Step 6.5: Commit**

```bash
git add src/tools/providers/sec_edgar.py tests/providers/test_sec_edgar_basics.py
git commit -m "feat(providers): add SEC EDGAR CIK resolver and filing date lookup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: SEC EDGAR — Form 4 XML parser

**Files:**
- Modify: `src/tools/providers/sec_edgar.py`
- Test: `tests/providers/test_sec_form4_parser.py`
- Test fixture: `tests/providers/fixtures/sec_form4_apple.xml`

- [ ] **Step 7.1: Create fixture XML**

Create `tests/providers/fixtures/sec_form4_apple.xml`:

```xml
<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0306</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2024-04-15</periodOfReport>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214156</rptOwnerCik>
      <rptOwnerName>COOK TIMOTHY D</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-04-15</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>170.50</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>3266000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
```

- [ ] **Step 7.2: Write the failing test**

Create `tests/providers/test_sec_form4_parser.py`:

```python
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
    assert t.is_board_director is False
    assert t.transaction_date == "2024-04-15"
    assert t.filing_date == "2024-04-17"
    assert t.transaction_shares == 10000
    assert t.transaction_price_per_share == 170.50
    # Form 4 transaction code "S" means sale; convention is negative shares
    assert t.transaction_value == 10000 * 170.50
    assert t.shares_owned_after_transaction == 3266000


def test_parse_form4_returns_empty_on_malformed_xml():
    trades = sec_edgar.parse_form4_xml("<not xml", ticker="AAPL", filing_date="2024-04-17")
    assert trades == []
```

- [ ] **Step 7.3: Run test to verify it fails**

Run: `pytest tests/providers/test_sec_form4_parser.py -v`
Expected: FAIL — `parse_form4_xml` not defined.

- [ ] **Step 7.4: Implement parse_form4_xml**

Append to `src/tools/providers/sec_edgar.py`:

```python


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
```

- [ ] **Step 7.5: Run tests to verify they pass**

Run: `pytest tests/providers/test_sec_form4_parser.py -v`
Expected: 2 PASS.

- [ ] **Step 7.6: Commit**

```bash
git add src/tools/providers/sec_edgar.py tests/providers/test_sec_form4_parser.py tests/providers/fixtures/
git commit -m "feat(providers): add Form 4 XML parser

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Alpha Vantage source — news + insider

**Files:**
- Create: `src/tools/providers/alpha_vantage.py`
- Test: `tests/providers/test_alpha_vantage.py`

- [ ] **Step 8.1: Write the failing test**

Create `tests/providers/test_alpha_vantage.py`:

```python
from unittest.mock import Mock, patch

import pytest

from src.tools.providers import alpha_vantage


def _av_news_payload():
    return {
        "feed": [
            {
                "title": "Apple beats earnings",
                "url": "https://example.com/a",
                "time_published": "20240501T120000",
                "source": "Reuters",
                "authors": ["Jane Doe"],
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_label": "Somewhat-Bullish"}
                ],
            },
            {
                "title": "Apple cuts forecast",
                "url": "https://example.com/b",
                "time_published": "20240502T120000",
                "source": "Bloomberg",
                "authors": [],
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_label": "Bearish"}
                ],
            },
        ]
    }


def test_fetch_news_normalizes_av_payload(yfinance_env):
    with patch.object(alpha_vantage, "_get_json", return_value=_av_news_payload()):
        news = alpha_vantage.fetch_news("AAPL", "2024-04-01", "2024-05-31", limit=10)

    assert len(news) == 2
    assert news[0].title == "Apple beats earnings"
    assert news[0].sentiment == "bullish"
    assert news[0].source == "Reuters"
    assert news[0].author == "Jane Doe"
    assert news[1].sentiment == "bearish"


def test_fetch_news_returns_none_on_rate_limit(yfinance_env):
    with patch.object(alpha_vantage, "_get_json", return_value={"Note": "Thank you for using Alpha Vantage"}):
        news = alpha_vantage.fetch_news("AAPL", "2024-04-01", "2024-05-31", limit=10)
    assert news is None  # signal to fallback


def test_fetch_insider_normalizes(yfinance_env):
    payload = {
        "data": [
            {
                "transaction_date": "2024-04-15",
                "ticker": "AAPL",
                "executive": "COOK TIMOTHY D",
                "executive_title": "CEO",
                "security_type": "Common Stock",
                "acquisition_or_disposal": "D",
                "shares": "10000",
                "share_price": "170.50",
            }
        ]
    }
    with patch.object(alpha_vantage, "_get_json", return_value=payload):
        trades = alpha_vantage.fetch_insider_trades("AAPL", "2024-01-01", "2024-12-31", limit=10)

    assert len(trades) == 1
    t = trades[0]
    assert t.name == "COOK TIMOTHY D"
    assert t.transaction_shares == -10000  # 'D' = disposal = negative
    assert t.transaction_price_per_share == 170.50
```

- [ ] **Step 8.2: Run test to verify it fails**

Run: `pytest tests/providers/test_alpha_vantage.py -v`
Expected: FAIL.

- [ ] **Step 8.3: Implement alpha_vantage.py**

Create `src/tools/providers/alpha_vantage.py`:

```python
"""Alpha Vantage client: NEWS_SENTIMENT (primary), INSIDER_TRANSACTIONS (fallback)."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from src.data.models import CompanyNews, InsiderTrade
from src.tools.providers import _config
from src.tools.providers._http import get_with_retry, make_session

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_RATE_LIMIT_SLEEP = 12  # 5 RPM = 12 seconds between calls


def _get_json(params: dict) -> dict | None:
    """GET against AV; return None if config missing or response invalid."""
    cfg = _config.load_config()
    if not cfg.alpha_vantage_api_key:
        return None
    s = make_session()
    time.sleep(_RATE_LIMIT_SLEEP)
    r = get_with_retry(s, _BASE, params={**params, "apikey": cfg.alpha_vantage_api_key})
    if r.status_code != 200:
        logger.warning("AV %s returned %s", params.get("function"), r.status_code)
        return None
    try:
        return r.json()
    except Exception as exc:
        logger.warning("AV JSON parse failed: %s", exc)
        return None


def _is_rate_limited(payload: dict) -> bool:
    return any(k in payload for k in ("Note", "Information"))


def _label_to_sentiment(label: str) -> str:
    label = label.lower()
    if "bullish" in label:
        return "bullish"
    if "bearish" in label:
        return "bearish"
    return "neutral"


def fetch_news(
    ticker: str, start_date: str, end_date: str, limit: int = 100
) -> list[CompanyNews] | None:
    """Return news with sentiment, or None to signal caller should fall back."""
    payload = _get_json({
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "limit": limit,
        "time_from": start_date.replace("-", "") + "T0000",
        "time_to": end_date.replace("-", "") + "T2359",
    })
    if payload is None:
        return None
    if _is_rate_limited(payload):
        logger.warning("AV rate-limited for %s news; fallback advised", ticker)
        return None

    out: list[CompanyNews] = []
    for item in payload.get("feed", []):
        sentiment = "neutral"
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker") == ticker:
                sentiment = _label_to_sentiment(ts.get("ticker_sentiment_label", ""))
                break
        authors = item.get("authors") or []
        out.append(
            CompanyNews(
                ticker=ticker,
                title=item.get("title", ""),
                author=authors[0] if authors else None,
                source=item.get("source", "alpha_vantage"),
                date=item.get("time_published", "")[:8],
                url=item.get("url", ""),
                sentiment=sentiment,
            )
        )
    return out


def fetch_insider_trades(
    ticker: str, start_date: str, end_date: str, limit: int = 1000
) -> list[InsiderTrade] | None:
    """Return insider trades; convention: negative shares for disposals.

    Returns None if AV unreachable or rate-limited.
    """
    payload = _get_json({"function": "INSIDER_TRANSACTIONS", "symbol": ticker})
    if payload is None or _is_rate_limited(payload):
        return None

    out: list[InsiderTrade] = []
    for row in payload.get("data", []):
        tx_date = row.get("transaction_date")
        if not tx_date or not (start_date <= tx_date <= end_date):
            continue
        try:
            shares = float(row.get("shares") or 0)
            price = float(row.get("share_price") or 0)
        except ValueError:
            continue
        is_disposal = row.get("acquisition_or_disposal") == "D"
        signed_shares = -shares if is_disposal else shares
        out.append(
            InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=row.get("executive"),
                title=row.get("executive_title"),
                is_board_director=None,
                transaction_date=tx_date,
                transaction_shares=signed_shares,
                transaction_price_per_share=price,
                transaction_value=signed_shares * price,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=row.get("security_type"),
                filing_date=tx_date,  # AV doesn't expose filing_date separately
            )
        )
    return out[:limit]
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_alpha_vantage.py -v`
Expected: 3 PASS.

- [ ] **Step 8.5: Commit**

```bash
git add src/tools/providers/alpha_vantage.py tests/providers/test_alpha_vantage.py
git commit -m "feat(providers): add Alpha Vantage news + insider client

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Bedrock sentiment annotator

**Files:**
- Create: `src/tools/providers/bedrock_sentiment.py`
- Test: `tests/providers/test_bedrock_sentiment.py`

- [ ] **Step 9.1: Write the failing test**

Create `tests/providers/test_bedrock_sentiment.py`:

```python
from unittest.mock import patch

from src.data.models import CompanyNews
from src.tools.providers import bedrock_sentiment


def _news(title: str) -> CompanyNews:
    return CompanyNews(
        ticker="AAPL", title=title, source="yfinance", date="2024-05-01",
        url="x", author=None, sentiment=None,
    )


def test_annotate_assigns_sentiment_per_title():
    fake_response = type(
        "R", (), {"content": '{"items":[{"i":0,"s":"bullish"},{"i":1,"s":"bearish"},{"i":2,"s":"neutral"}]}'}
    )()

    with patch.object(bedrock_sentiment, "_invoke_haiku", return_value=fake_response.content):
        news_in = [_news("Apple soars"), _news("Apple plunges"), _news("Apple holds steady")]
        out = bedrock_sentiment.annotate(news_in)

    assert out[0].sentiment == "bullish"
    assert out[1].sentiment == "bearish"
    assert out[2].sentiment == "neutral"


def test_annotate_empty_list_returns_empty():
    assert bedrock_sentiment.annotate([]) == []


def test_annotate_falls_back_to_neutral_on_invoke_error():
    with patch.object(bedrock_sentiment, "_invoke_haiku", side_effect=RuntimeError("boom")):
        out = bedrock_sentiment.annotate([_news("Apple soars")])
    assert out[0].sentiment == "neutral"
```

- [ ] **Step 9.2: Run test to verify it fails**

Run: `pytest tests/providers/test_bedrock_sentiment.py -v`
Expected: FAIL.

- [ ] **Step 9.3: Implement bedrock_sentiment.py**

Create `src/tools/providers/bedrock_sentiment.py`:

```python
"""Batch sentiment annotation via Bedrock Haiku 4.5.

Reuses the existing ChatBedrockConverse path from src.llm.models.
"""

from __future__ import annotations

import json
import logging

from src.data.models import CompanyNews

logger = logging.getLogger(__name__)

_HAIKU_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_HAIKU_REGION_DEFAULT = "us-east-1"

_PROMPT = (
    "Classify each news title's sentiment toward the listed ticker. "
    "Return ONLY a JSON object with this exact shape: "
    '{"items":[{"i":<int>,"s":"bullish|bearish|neutral"}]}. '
    "No prose. No code fences."
)


def _invoke_haiku(prompt: str) -> str:
    """Call Haiku via the existing get_model path; return raw content."""
    from src.llm.models import ModelProvider, get_model
    llm = get_model(_HAIKU_MODEL, ModelProvider.BEDROCK)
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def annotate(news: list[CompanyNews]) -> list[CompanyNews]:
    """Set news[i].sentiment in-place. On any error, default to 'neutral'."""
    if not news:
        return news

    items_block = "\n".join(
        f"{i}. ticker={n.ticker} title={json.dumps(n.title)}"
        for i, n in enumerate(news)
    )
    full_prompt = f"{_PROMPT}\n\nItems:\n{items_block}"

    try:
        raw = _invoke_haiku(full_prompt)
        # Strip code fences if model added them
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(raw)
        labels = {item["i"]: item["s"] for item in parsed.get("items", [])}
    except Exception as exc:
        logger.warning("Bedrock sentiment annotation failed: %s", exc)
        for n in news:
            if n.sentiment is None:
                n.sentiment = "neutral"
        return news

    for i, n in enumerate(news):
        n.sentiment = labels.get(i, "neutral")
    return news
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_bedrock_sentiment.py -v`
Expected: 3 PASS.

- [ ] **Step 9.5: Commit**

```bash
git add src/tools/providers/bedrock_sentiment.py tests/providers/test_bedrock_sentiment.py
git commit -m "feat(providers): add Bedrock Haiku sentiment annotator

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Derived layer — TTM composer

**Files:**
- Create: `src/tools/providers/derived.py` (initial)
- Test: `tests/providers/test_derived_ttm.py`

- [ ] **Step 10.1: Write the failing test**

Create `tests/providers/test_derived_ttm.py`:

```python
from src.tools.providers import derived


def _quarters():
    """Return 5 quarters newest-first; flow values 100/90/85/80/75."""
    return [
        {"report_period": "2024-03-31", "revenue": 100, "net_income": 20,
         "total_assets": 1000, "shareholders_equity": 400, "outstanding_shares": 100,
         "free_cash_flow": 18, "ebitda": 30, "ebit": 25, "interest_expense": 2,
         "operating_income": 25, "gross_profit": 40,
         "current_assets": 300, "current_liabilities": 150, "total_liabilities": 600,
         "cash_and_equivalents": 50, "total_debt": 200, "depreciation_and_amortization": 8,
         "capital_expenditure": 5, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.20,
         "research_and_development": 5, "operating_expense": 15,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-12-31", "revenue": 90,  "net_income": 15,
         "total_assets": 900,  "shareholders_equity": 380, "outstanding_shares": 100,
         "free_cash_flow": 14, "ebitda": 22, "ebit": 18, "interest_expense": 2,
         "operating_income": 20, "gross_profit": 35,
         "current_assets": 280, "current_liabilities": 140, "total_liabilities": 540,
         "cash_and_equivalents": 45, "total_debt": 210, "depreciation_and_amortization": 7,
         "capital_expenditure": 4, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.15,
         "research_and_development": 4, "operating_expense": 14,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-09-30", "revenue": 85,  "net_income": 14,
         "total_assets": 850, "shareholders_equity": 360, "outstanding_shares": 100,
         "free_cash_flow": 12, "ebitda": 20, "ebit": 17, "interest_expense": 2,
         "operating_income": 19, "gross_profit": 33,
         "current_assets": 270, "current_liabilities": 135, "total_liabilities": 510,
         "cash_and_equivalents": 40, "total_debt": 220, "depreciation_and_amortization": 7,
         "capital_expenditure": 4, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.14,
         "research_and_development": 4, "operating_expense": 13,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-06-30", "revenue": 80,  "net_income": 12,
         "total_assets": 800, "shareholders_equity": 340, "outstanding_shares": 100,
         "free_cash_flow": 10, "ebitda": 18, "ebit": 15, "interest_expense": 2,
         "operating_income": 17, "gross_profit": 30,
         "current_assets": 260, "current_liabilities": 130, "total_liabilities": 480,
         "cash_and_equivalents": 35, "total_debt": 230, "depreciation_and_amortization": 6,
         "capital_expenditure": 3, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.12,
         "research_and_development": 3, "operating_expense": 12,
         "goodwill_and_intangible_assets": 50},
        {"report_period": "2023-03-31", "revenue": 75,  "net_income": 10,
         "total_assets": 750, "shareholders_equity": 320, "outstanding_shares": 100,
         "free_cash_flow": 8, "ebitda": 16, "ebit": 13, "interest_expense": 2,
         "operating_income": 15, "gross_profit": 28,
         "current_assets": 250, "current_liabilities": 125, "total_liabilities": 450,
         "cash_and_equivalents": 30, "total_debt": 240, "depreciation_and_amortization": 6,
         "capital_expenditure": 3, "dividends_and_other_cash_distributions": 3,
         "issuance_or_purchase_of_equity_shares": 0, "earnings_per_share": 0.10,
         "research_and_development": 3, "operating_expense": 11,
         "goodwill_and_intangible_assets": 50},
    ]


def test_compose_ttm_sums_flow_fields():
    ttm = derived.compose_ttm(_quarters()[:4])
    assert ttm["revenue"] == 100 + 90 + 85 + 80
    assert ttm["net_income"] == 20 + 15 + 14 + 12
    assert ttm["free_cash_flow"] == 18 + 14 + 12 + 10


def test_compose_ttm_uses_latest_for_stock_fields():
    ttm = derived.compose_ttm(_quarters()[:4])
    # Stock fields = latest BS
    assert ttm["total_assets"] == 1000
    assert ttm["shareholders_equity"] == 400
    assert ttm["outstanding_shares"] == 100


def test_compose_ttm_returns_none_with_fewer_than_4_quarters():
    assert derived.compose_ttm(_quarters()[:3]) is None
```

- [ ] **Step 10.2: Run test to verify it fails**

Run: `pytest tests/providers/test_derived_ttm.py -v`
Expected: FAIL.

- [ ] **Step 10.3: Implement compose_ttm**

Create `src/tools/providers/derived.py`:

```python
"""Derived layer: TTM composer + PIT market_cap + 41 self-computed ratios.

Single contract:
- compose_ttm(quarters) -> dict | None
- compute_market_cap_pit(...)
- compute_financial_metrics(...)

All callers expect None on insufficient/invalid data; never raises.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Income statement and cash flow flows: sum across 4 quarters
FLOW_FIELDS: set[str] = {
    "revenue", "gross_profit", "operating_income", "operating_expense",
    "net_income", "ebit", "ebitda", "interest_expense",
    "free_cash_flow", "capital_expenditure", "depreciation_and_amortization",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "research_and_development", "earnings_per_share",
}

# Balance sheet stocks: take latest period
STOCK_FIELDS: set[str] = {
    "total_assets", "current_assets", "cash_and_equivalents",
    "total_liabilities", "current_liabilities", "total_debt",
    "shareholders_equity", "outstanding_shares",
    "goodwill_and_intangible_assets",
}


def compose_ttm(quarters: list[dict]) -> dict | None:
    """Build a TTM record from at least 4 newest-first quarterly dicts.

    Returns None if fewer than 4 quarters available.
    """
    if not quarters or len(quarters) < 4:
        return None
    latest = quarters[0]
    last4 = quarters[:4]

    out: dict[str, Any] = {
        "ticker": latest.get("ticker"),
        "report_period": latest["report_period"],
        "period": "ttm",
        "currency": latest.get("currency", "USD"),
    }

    for field in FLOW_FIELDS:
        vals = [q.get(field) for q in last4]
        present = [v for v in vals if v is not None]
        out[field] = sum(present) if present else None

    for field in STOCK_FIELDS:
        out[field] = latest.get(field)

    return out
```

- [ ] **Step 10.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_derived_ttm.py -v`
Expected: 3 PASS.

- [ ] **Step 10.5: Commit**

```bash
git add src/tools/providers/derived.py tests/providers/test_derived_ttm.py
git commit -m "feat(providers): add TTM composer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Derived layer — PIT filter

**Files:**
- Modify: `src/tools/providers/derived.py`
- Test: `tests/providers/test_derived_pit.py`

- [ ] **Step 11.1: Write the failing test**

Create `tests/providers/test_derived_pit.py`:

```python
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
```

- [ ] **Step 11.2: Run test to verify it fails**

Run: `pytest tests/providers/test_derived_pit.py -v`
Expected: FAIL — `filter_pit` not defined.

- [ ] **Step 11.3: Implement filter_pit**

Append to `src/tools/providers/derived.py`:

```python


def filter_pit(
    quarters: list[dict],
    filing_dates: dict[str, str],
    *,
    decision_date: str,
) -> list[dict]:
    """Keep only quarters whose filing_date <= decision_date.

    Drops periods missing from filing_dates (per spec: never assume future).
    """
    kept: list[dict] = []
    for q in quarters:
        rp = q.get("report_period")
        if not rp:
            continue
        fd = filing_dates.get(rp)
        if fd is None:
            continue
        if fd > decision_date:
            continue
        kept.append(q)
    return kept
```

- [ ] **Step 11.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_derived_pit.py -v`
Expected: 3 PASS.

- [ ] **Step 11.5: Commit**

```bash
git add src/tools/providers/derived.py tests/providers/test_derived_pit.py
git commit -m "feat(providers): add strict PIT filter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Derived layer — financial metrics computation

**Files:**
- Modify: `src/tools/providers/derived.py`
- Test: `tests/providers/test_derived_metrics.py`

- [ ] **Step 12.1: Write the failing tests**

Create `tests/providers/test_derived_metrics.py`:

```python
from src.tools.providers import derived


def test_safe_div_handles_zero_and_none():
    assert derived.safe_div(10, 2) == 5.0
    assert derived.safe_div(10, 0) is None
    assert derived.safe_div(None, 5) is None
    assert derived.safe_div(10, None) is None


def _ttm_curr():
    return {
        "revenue": 400, "gross_profit": 160, "operating_income": 80, "net_income": 60,
        "ebit": 80, "ebitda": 100, "interest_expense": 10,
        "free_cash_flow": 50, "capital_expenditure": 20,
        "earnings_per_share": 0.60,
        "total_assets": 1000, "current_assets": 300, "cash_and_equivalents": 50,
        "total_liabilities": 600, "current_liabilities": 150, "total_debt": 200,
        "shareholders_equity": 400, "outstanding_shares": 100,
    }


def _ttm_prev():
    base = _ttm_curr()
    base["revenue"] = 320
    base["net_income"] = 48
    base["free_cash_flow"] = 40
    base["ebitda"] = 80
    base["operating_income"] = 64
    base["shareholders_equity"] = 350
    return base


def test_compute_ratios_basic():
    fm = derived.compute_metrics(
        _ttm_curr(), prev_ttm=_ttm_prev(), market_cap=12000, ticker="AAPL",
    )
    assert fm.gross_margin == 0.4
    assert fm.operating_margin == 0.2
    assert fm.net_margin == 0.15
    assert fm.return_on_equity == 60 / 400
    assert fm.return_on_assets == 60 / 1000
    assert fm.current_ratio == 2.0
    assert fm.debt_to_equity == 0.5
    assert fm.interest_coverage == 8.0
    assert fm.price_to_earnings_ratio == 12000 / 60
    assert fm.price_to_book_ratio == 12000 / 400
    assert fm.price_to_sales_ratio == 12000 / 400


def test_growth_uses_4_quarters_back():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=None, ticker="AAPL")
    assert fm.revenue_growth == (400 / 320) - 1
    assert fm.earnings_growth == (60 / 48) - 1
    assert fm.free_cash_flow_growth == (50 / 40) - 1
    assert fm.ebitda_growth == (100 / 80) - 1


def test_partial_fill_when_market_cap_missing():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=None, ticker="AAPL")
    assert fm.market_cap is None
    assert fm.price_to_earnings_ratio is None
    # Non-price fields still populated
    assert fm.gross_margin == 0.4
    assert fm.return_on_equity == 60 / 400


def test_roic_formula():
    fm = derived.compute_metrics(_ttm_curr(), prev_ttm=_ttm_prev(), market_cap=12000, ticker="AAPL")
    # nopat = ebit*(1-0.21) = 80*0.79 = 63.2
    # invested_capital = total_debt + equity - cash = 200 + 400 - 50 = 550
    assert fm.return_on_invested_capital == 63.2 / 550
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `pytest tests/providers/test_derived_metrics.py -v`
Expected: FAIL — `compute_metrics` not defined.

- [ ] **Step 12.3: Implement safe_div + compute_metrics**

Append to `src/tools/providers/derived.py`:

```python


def safe_div(num, den):
    """Divide; return None on zero/None operand or NaN/inf result."""
    if num is None or den in (None, 0):
        return None
    try:
        result = num / den
    except ZeroDivisionError:
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _growth(curr, prev):
    if curr is None or prev in (None, 0):
        return None
    return curr / prev - 1


def compute_metrics(ttm: dict, *, prev_ttm: dict | None, market_cap: float | None,
                    ticker: str, currency: str = "USD") -> "FinancialMetrics":
    """Build a FinancialMetrics from TTM, previous TTM, and PIT market cap.

    All 41 fields are filled where possible; missing dependencies → None
    (partial fill).
    """
    from src.data.models import FinancialMetrics

    rev = ttm.get("revenue")
    ni = ttm.get("net_income")
    ebit = ttm.get("ebit")
    ebitda = ttm.get("ebitda")
    op_inc = ttm.get("operating_income")
    gross = ttm.get("gross_profit")
    fcf = ttm.get("free_cash_flow")
    ie = ttm.get("interest_expense")
    eps = ttm.get("earnings_per_share")
    capex = ttm.get("capital_expenditure")

    assets = ttm.get("total_assets")
    ca = ttm.get("current_assets")
    cash = ttm.get("cash_and_equivalents")
    cl = ttm.get("current_liabilities")
    debt = ttm.get("total_debt")
    equity = ttm.get("shareholders_equity")
    shares = ttm.get("outstanding_shares")
    tl = ttm.get("total_liabilities")

    # Enterprise value: market_cap + debt - cash
    ev = None
    if market_cap is not None:
        ev = market_cap + (debt or 0) - (cash or 0)

    # ROIC: NOPAT / invested_capital
    tax_rate = 0.21
    nopat = ebit * (1 - tax_rate) if ebit is not None else None
    invested_capital = None
    if debt is not None and equity is not None:
        invested_capital = debt + equity - (cash or 0)
    roic = safe_div(nopat, invested_capital)

    # Growth fields (4Q back)
    prev = prev_ttm or {}

    return FinancialMetrics(
        ticker=ticker,
        report_period=ttm.get("report_period"),
        period=ttm.get("period", "ttm"),
        currency=currency,
        market_cap=market_cap,
        enterprise_value=ev,
        # Valuation
        price_to_earnings_ratio=safe_div(market_cap, ni),
        price_to_book_ratio=safe_div(market_cap, equity),
        price_to_sales_ratio=safe_div(market_cap, rev),
        enterprise_value_to_ebitda_ratio=safe_div(ev, ebitda),
        enterprise_value_to_revenue_ratio=safe_div(ev, rev),
        free_cash_flow_yield=safe_div(fcf, market_cap),
        peg_ratio=safe_div(safe_div(market_cap, ni), _growth(ni, prev.get("net_income")) or None),
        # Profitability
        gross_margin=safe_div(gross, rev),
        operating_margin=safe_div(op_inc, rev),
        net_margin=safe_div(ni, rev),
        return_on_equity=safe_div(ni, equity),
        return_on_assets=safe_div(ni, assets),
        return_on_invested_capital=roic,
        # Efficiency
        asset_turnover=safe_div(rev, assets),
        inventory_turnover=None,
        receivables_turnover=None,
        days_sales_outstanding=None,
        operating_cycle=None,
        working_capital_turnover=None,
        # Liquidity
        current_ratio=safe_div(ca, cl),
        quick_ratio=safe_div((ca or 0) - 0, cl) if ca is not None else None,
        cash_ratio=safe_div(cash, cl),
        operating_cash_flow_ratio=safe_div(fcf, cl),
        # Leverage
        debt_to_equity=safe_div(debt, equity),
        debt_to_assets=safe_div(debt, assets),
        interest_coverage=safe_div(ebit, abs(ie) if ie else None),
        # Growth
        revenue_growth=_growth(rev, prev.get("revenue")),
        earnings_growth=_growth(ni, prev.get("net_income")),
        book_value_growth=_growth(equity, prev.get("shareholders_equity")),
        earnings_per_share_growth=_growth(eps, prev.get("earnings_per_share")),
        free_cash_flow_growth=_growth(fcf, prev.get("free_cash_flow")),
        operating_income_growth=_growth(op_inc, prev.get("operating_income")),
        ebitda_growth=_growth(ebitda, prev.get("ebitda")),
        # Per-share
        payout_ratio=None,
        earnings_per_share=eps,
        book_value_per_share=safe_div(equity, shares),
        free_cash_flow_per_share=safe_div(fcf, shares),
    )
```

- [ ] **Step 12.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_derived_metrics.py -v`
Expected: 5 PASS.

- [ ] **Step 12.5: Commit**

```bash
git add src/tools/providers/derived.py tests/providers/test_derived_metrics.py
git commit -m "feat(providers): add 41-field financial metrics computation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Derived layer — PIT market cap + line items orchestration

**Files:**
- Modify: `src/tools/providers/derived.py`
- Test: `tests/providers/test_derived_market_cap.py`

- [ ] **Step 13.1: Write the failing test**

Create `tests/providers/test_derived_market_cap.py`:

```python
from unittest.mock import patch

from src.data.models import Price
from src.tools.providers import derived


def test_market_cap_is_close_times_shares():
    fake_prices = [Price(open=1, high=2, low=1, close=170.5, volume=1, time="2024-06-28")]
    fake_quarters = [
        {"report_period": "2024-03-31", "outstanding_shares": 15_000_000_000},
    ]
    with patch.object(derived, "_fetch_prices_window", return_value=fake_prices), \
         patch.object(derived, "_fetch_pit_quarters", return_value=fake_quarters):
        mc = derived.compute_market_cap_pit("AAPL", end_date="2024-06-30")
    assert mc == 170.5 * 15_000_000_000


def test_market_cap_returns_none_without_shares():
    fake_prices = [Price(open=1, high=2, low=1, close=170.5, volume=1, time="2024-06-28")]
    with patch.object(derived, "_fetch_prices_window", return_value=fake_prices), \
         patch.object(derived, "_fetch_pit_quarters", return_value=[]):
        assert derived.compute_market_cap_pit("AAPL", end_date="2024-06-30") is None


def test_market_cap_returns_none_without_close():
    with patch.object(derived, "_fetch_prices_window", return_value=[]), \
         patch.object(derived, "_fetch_pit_quarters", return_value=[{"outstanding_shares": 1}]):
        assert derived.compute_market_cap_pit("AAPL", end_date="2024-06-30") is None
```

- [ ] **Step 13.2: Run test to verify it fails**

Run: `pytest tests/providers/test_derived_market_cap.py -v`
Expected: FAIL.

- [ ] **Step 13.3: Implement compute_market_cap_pit + helpers**

Append to `src/tools/providers/derived.py`:

```python


def _fetch_prices_window(ticker: str, end_date: str):
    """Fetch up to 7 days of prices ending at end_date for last-close lookup."""
    from datetime import datetime, timedelta
    from src.tools.providers import yfinance_source

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=7)
    return yfinance_source.fetch_prices(
        ticker, start_dt.strftime("%Y-%m-%d"), end_date,
    )


def _fetch_pit_quarters(ticker: str, end_date: str) -> list[dict]:
    """Fetch quarterly statements + apply PIT filter via SEC filing dates."""
    from src.tools.providers import sec_edgar, yfinance_source

    quarters = yfinance_source.fetch_quarterly_statements(ticker)
    if not quarters:
        return []
    cik = sec_edgar.resolve_cik(ticker)
    if cik is None:
        logger.warning(
            "SEC CIK lookup failed for %s — dropping all quarters per strict PIT", ticker,
        )
        return []
    filing_dates = sec_edgar.get_filing_dates(cik)
    if not filing_dates:
        return []
    return filter_pit(quarters, filing_dates, decision_date=end_date)


def compute_market_cap_pit(ticker: str, end_date: str) -> float | None:
    """Return close-price × shares-outstanding as of end_date, or None."""
    prices = _fetch_prices_window(ticker, end_date)
    if not prices:
        return None
    last_close = prices[-1].close

    quarters = _fetch_pit_quarters(ticker, end_date)
    if not quarters:
        return None
    shares = quarters[0].get("outstanding_shares")
    if shares is None:
        return None
    return last_close * shares
```

- [ ] **Step 13.4: Run tests to verify they pass**

Run: `pytest tests/providers/test_derived_market_cap.py -v`
Expected: 3 PASS.

- [ ] **Step 13.5: Commit**

```bash
git add src/tools/providers/derived.py tests/providers/test_derived_market_cap.py
git commit -m "feat(providers): add PIT market cap computation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Dispatch layer

**Files:**
- Create: `src/tools/providers/dispatch.py`
- Test: `tests/providers/test_dispatch.py`

- [ ] **Step 14.1: Write the failing test**

Create `tests/providers/test_dispatch.py`:

```python
from unittest.mock import MagicMock, patch

from src.data.models import (CompanyNews, FinancialMetrics, InsiderTrade,
                              LineItem, Price)
from src.tools.providers import dispatch


def test_fetch_prices_delegates_to_yfinance(yfinance_env):
    with patch("src.tools.providers.dispatch.yfinance_source.fetch_prices",
               return_value=[Price(open=1, high=1, low=1, close=1, volume=1, time="2024-01-02")]) as m:
        out = dispatch.fetch_prices("AAPL", "2024-01-01", "2024-01-05")
    m.assert_called_once_with("AAPL", "2024-01-01", "2024-01-05")
    assert len(out) == 1


def test_fetch_company_news_uses_av_first_then_falls_back(yfinance_env):
    fake_yf_titles = [
        CompanyNews(ticker="AAPL", title="t1", source="yf", date="2024-05-01",
                    url="x", sentiment=None),
    ]

    with patch("src.tools.providers.dispatch.alpha_vantage.fetch_news", return_value=None) as av, \
         patch("src.tools.providers.dispatch.yfinance_source.fetch_news_titles",
               return_value=fake_yf_titles) as yf, \
         patch("src.tools.providers.dispatch.bedrock_sentiment.annotate",
               side_effect=lambda news: [n.model_copy(update={"sentiment": "neutral"}) for n in news]) as bd:
        out = dispatch.fetch_company_news("AAPL", "2024-05-01", "2024-05-31", limit=10)

    av.assert_called_once()
    yf.assert_called_once()
    bd.assert_called_once()
    assert out[0].sentiment == "neutral"


def test_fetch_insider_trades_falls_back_to_av(yfinance_env):
    av_trades = [InsiderTrade(ticker="AAPL", filing_date="2024-04-15", name="x",
                              issuer=None, title=None, is_board_director=None,
                              transaction_date="2024-04-15", transaction_shares=-100,
                              transaction_price_per_share=170.0,
                              transaction_value=-17000.0,
                              shares_owned_before_transaction=None,
                              shares_owned_after_transaction=None,
                              security_title="Common")]
    with patch("src.tools.providers.dispatch.sec_edgar.fetch_form4_trades", return_value=[]), \
         patch("src.tools.providers.dispatch.alpha_vantage.fetch_insider_trades",
               return_value=av_trades) as av:
        out = dispatch.fetch_insider_trades("AAPL", end_date="2024-06-30",
                                            start_date="2024-01-01", limit=10)
    av.assert_called_once()
    assert len(out) == 1
```

- [ ] **Step 14.2: Run test to verify it fails**

Run: `pytest tests/providers/test_dispatch.py -v`
Expected: FAIL.

- [ ] **Step 14.3: Add helper to yfinance_source for news titles**

Append to `src/tools/providers/yfinance_source.py`:

```python


def fetch_news_titles(ticker: str, start_date: str, end_date: str, limit: int = 50):
    """Best-effort: pull recent news titles via yfinance (no sentiment).

    Returns list of CompanyNews with sentiment=None. Caller annotates downstream.
    """
    from src.data.models import CompanyNews

    try:
        items = yf.Ticker(ticker).news or []
    except Exception as exc:
        logger.warning("yfinance news failed for %s: %s", ticker, exc)
        return []

    out: list[CompanyNews] = []
    for it in items[:limit]:
        # Schema varies; defensively pull
        title = it.get("title") or it.get("content", {}).get("title", "")
        link = it.get("link") or it.get("content", {}).get("canonicalUrl", {}).get("url", "")
        publisher = it.get("publisher") or it.get("content", {}).get("provider", {}).get("displayName", "yfinance")
        ts = it.get("providerPublishTime")
        date = ""
        if isinstance(ts, (int, float)):
            from datetime import datetime, timezone
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if not title:
            continue
        if start_date and date and date < start_date:
            continue
        if end_date and date and date > end_date:
            continue
        out.append(CompanyNews(
            ticker=ticker, title=title, author=None, source=publisher,
            date=date, url=link, sentiment=None,
        ))
    return out
```

- [ ] **Step 14.4: Add helper to sec_edgar for full Form 4 fetching**

Append to `src/tools/providers/sec_edgar.py`:

```python


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
        url = f"{_BASE_FILES}/Archives/edgar/data/{int(cik10)}/{acc_clean}/{doc}"
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
```

- [ ] **Step 14.5: Implement dispatch.py**

Create `src/tools/providers/dispatch.py`:

```python
"""Dispatch layer: hard-coded fallback chains for the 6 public entries."""

from __future__ import annotations

import logging
from typing import Any

from src.data.models import (CompanyNews, FinancialMetrics, InsiderTrade,
                              LineItem, Price)
from src.tools.providers import (alpha_vantage, bedrock_sentiment, derived,
                                  sec_edgar, yfinance_source)
from src.tools.providers._cache import Cache
from src.tools.providers._config import banner, load_config

logger = logging.getLogger(__name__)
_BANNER_PRINTED = False
_CACHE: Cache | None = None


def _emit_banner_once() -> None:
    global _BANNER_PRINTED
    if _BANNER_PRINTED:
        return
    cfg = load_config()
    logger.info(banner(cfg))
    print(banner(cfg))
    _BANNER_PRINTED = True


def _cache() -> Cache:
    global _CACHE
    if _CACHE is None:
        cfg = load_config()
        _CACHE = Cache(cfg.cache_dir / "providers.db")
    return _CACHE


def _cached(key: str, ttl: int, fn):
    """Look up `key` in the SQLite cache; on miss, call fn(), store, return."""
    c = _cache()
    hit = c.get(key)
    if hit is not None:
        return hit
    val = fn()
    if val is not None:
        c.set(key, val, ttl)
    return val


# -------------------- public dispatch functions --------------------

def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    _emit_banner_once()
    key = f"yfinance:prices:{ticker}:{start_date}:{end_date}:day:v1"
    return _cached(key, 0, lambda: yfinance_source.fetch_prices(ticker, start_date, end_date)) or []


def fetch_line_items(ticker: str, end_date: str, period: str, limit: int) -> list[LineItem]:
    _emit_banner_once()
    key = f"yfinance:line_items:{ticker}::{end_date}:{period}:{limit}:v1"

    def _build():
        quarters = derived._fetch_pit_quarters(ticker, end_date)
        out: list[LineItem] = []
        for q in quarters[:limit]:
            try:
                out.append(LineItem(**q))
            except Exception as exc:
                logger.warning("LineItem validation failed for %s/%s: %s", ticker, q.get("report_period"), exc)
        return out

    return _cached(key, 7 * 86400, _build) or []


def fetch_financial_metrics(
    ticker: str, end_date: str, period: str, limit: int
) -> list[FinancialMetrics]:
    _emit_banner_once()
    key = f"derived:financial_metrics:{ticker}::{end_date}:{period}:{limit}:v1"

    def _build():
        quarters = derived._fetch_pit_quarters(ticker, end_date)
        if len(quarters) < 4:
            return []
        ttm_curr = derived.compose_ttm(quarters)
        ttm_prev = derived.compose_ttm(quarters[4:8]) if len(quarters) >= 8 else None
        market_cap = derived.compute_market_cap_pit(ticker, end_date)
        fm = derived.compute_metrics(
            ttm_curr, prev_ttm=ttm_prev, market_cap=market_cap, ticker=ticker,
        )
        return [fm][:limit]

    return _cached(key, 7 * 86400, _build) or []


def fetch_market_cap(ticker: str, end_date: str) -> float | None:
    _emit_banner_once()
    key = f"derived:market_cap_pit:{ticker}::{end_date}::v1"
    return _cached(key, 7 * 86400,
                   lambda: derived.compute_market_cap_pit(ticker, end_date))


def fetch_company_news(
    ticker: str, end_date: str, start_date: str | None, limit: int
) -> list[CompanyNews]:
    _emit_banner_once()
    sd = start_date or "1970-01-01"
    key = f"news:{ticker}:{sd}:{end_date}:{limit}:v1"

    def _build():
        # Primary: Alpha Vantage with sentiment
        out = alpha_vantage.fetch_news(ticker, sd, end_date, limit)
        if out is not None:
            return out
        # Fallback: yfinance titles + Bedrock sentiment
        titles = yfinance_source.fetch_news_titles(ticker, sd, end_date, limit)
        if not titles:
            return []
        return bedrock_sentiment.annotate(titles)

    return _cached(key, 86400, _build) or []


def fetch_insider_trades(
    ticker: str, end_date: str, start_date: str | None, limit: int
) -> list[InsiderTrade]:
    _emit_banner_once()
    sd = start_date or "1970-01-01"
    key = f"insider:{ticker}:{sd}:{end_date}:{limit}:v1"

    def _build():
        # Primary: SEC EDGAR Form 4
        try:
            sec_trades = sec_edgar.fetch_form4_trades(ticker, sd, end_date, limit)
        except Exception as exc:
            logger.warning("SEC Form 4 fetch failed for %s: %s", ticker, exc)
            sec_trades = []
        if sec_trades:
            return sec_trades
        # Fallback: Alpha Vantage
        av_trades = alpha_vantage.fetch_insider_trades(ticker, sd, end_date, limit)
        return av_trades or []

    return _cached(key, 86400, _build) or []
```

- [ ] **Step 14.6: Run tests to verify they pass**

Run: `pytest tests/providers/test_dispatch.py -v`
Expected: 3 PASS.

- [ ] **Step 14.7: Commit**

```bash
git add src/tools/providers/dispatch.py src/tools/providers/yfinance_source.py src/tools/providers/sec_edgar.py tests/providers/test_dispatch.py
git commit -m "feat(providers): add dispatch layer with fallback chains

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Wire api.py to dispatch (the main contract preservation step)

**Files:**
- Modify: `src/tools/api.py`
- Test: `tests/providers/test_dispatch_routing.py`

- [ ] **Step 15.1: Write the failing test**

Create `tests/providers/test_dispatch_routing.py`:

```python
"""Routing contract: api.py honours DATA_PROVIDER without breaking FD mode."""

import pytest

from src.tools import api


def test_fd_mode_default_does_not_import_providers(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    # Sanity: providers package was never auto-imported by api.py module load
    import sys
    # we don't strictly enforce 'never imported' (test order makes that brittle);
    # what we DO enforce is that api.get_prices in FD mode does NOT call dispatch:
    called = {"dispatch": False}

    def boom(*a, **k):
        called["dispatch"] = True
        raise AssertionError("dispatch should not be called in FD mode")

    monkeypatch.setattr("src.tools.providers.dispatch.fetch_prices", boom, raising=False)

    # FD path tries to hit the network; we stub _make_api_request to short-circuit.
    monkeypatch.setattr(api, "_make_api_request",
                        lambda *a, **kw: type("R", (), {"status_code": 500, "json": lambda self: {}})())
    result = api.get_prices("AAPL", "2024-01-01", "2024-01-05")
    assert result == []  # FD path returned empty due to 500
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
```

- [ ] **Step 15.2: Run test to verify it fails**

Run: `pytest tests/providers/test_dispatch_routing.py -v`
Expected: Some tests FAIL because api.py doesn't yet route.

- [ ] **Step 15.3: Modify api.py — add 4-line branch to each of the 6 functions**

For each of: `get_prices`, `get_financial_metrics`, `search_line_items`, `get_insider_trades`, `get_company_news`, `get_market_cap` — insert at the top of the function body, before any existing code:

For `get_prices`:
```python
def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch price data from cache or API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_prices(ticker, start_date, end_date)

    # Create a cache key that includes all parameters to ensure exact matches
    cache_key = f"{ticker}_{start_date}_{end_date}"
    # ... rest of original code unchanged ...
```

For `get_financial_metrics`:
```python
def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_financial_metrics(ticker, end_date, period, limit)

    # ... rest of original code unchanged ...
```

For `search_line_items`:
```python
def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Fetch line items from API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_line_items(ticker, end_date, period, limit)

    # ... rest of original code unchanged ...
```

For `get_insider_trades`:
```python
def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider trades from cache or API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_insider_trades(ticker, end_date, start_date, limit)

    # ... rest of original code unchanged ...
```

For `get_company_news`:
```python
def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    """Fetch company news from cache or API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_company_news(ticker, end_date, start_date, limit)

    # ... rest of original code unchanged ...
```

For `get_market_cap`:
```python
def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap from the API."""
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_market_cap(ticker, end_date)

    # ... rest of original code unchanged ...
```

**Important**: only insert the 4-line branch at the very top of each function body. Do NOT delete or reorder any existing FD code.

- [ ] **Step 15.4: Run all unit tests to verify nothing broke**

Run: `pytest tests/providers/ tests/test_cache.py tests/test_api_rate_limiting.py -v`
Expected: All PASS — old FD-mode tests still green, new routing tests now pass.

- [ ] **Step 15.5: Commit**

```bash
git add src/tools/api.py tests/providers/test_dispatch_routing.py
git commit -m "feat(api): route to providers.dispatch when DATA_PROVIDER=yfinance

Six public entries gain a 4-line top-of-body env switch; default
financial_datasets path remains byte-for-byte identical.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Smoke integration test (live)

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_yfinance_smoke.py`
- Modify: `pyproject.toml` (register `live` marker)

- [ ] **Step 16.1: Register the live marker**

In `pyproject.toml`, add (or append within existing `[tool.pytest.ini_options]`):

```toml
[tool.pytest.ini_options]
markers = [
    "live: tests that hit real external services; require network and may be slow",
]
```

If `[tool.pytest.ini_options]` already exists, just add the `markers` key.

- [ ] **Step 16.2: Create the smoke test**

Create `tests/integration/__init__.py` (empty).

Create `tests/integration/test_yfinance_smoke.py`:

```python
"""Live end-to-end smoke test for yfinance provider stack.

Run with: pytest tests/integration/test_yfinance_smoke.py -m live

Requires:
- Internet connectivity
- SEC_EDGAR_USER_AGENT set in .env
- Optional: ALPHAVANTAGE_API_KEY, AWS_BEARER_TOKEN_BEDROCK
"""

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def force_yfinance_provider(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yfinance")
    if not os.getenv("SEC_EDGAR_USER_AGENT"):
        pytest.skip("SEC_EDGAR_USER_AGENT not set")


def test_get_prices_returns_data():
    from src.tools.api import get_prices
    prices = get_prices("AAPL", "2024-06-01", "2024-06-30")
    assert len(prices) > 5
    assert all(p.close > 0 for p in prices)


def test_get_financial_metrics_returns_at_least_partial():
    from src.tools.api import get_financial_metrics
    metrics = get_financial_metrics("AAPL", "2024-06-30", period="ttm", limit=1)
    assert len(metrics) == 1
    # Margins should populate even if market_cap weren't available
    assert metrics[0].gross_margin is not None


def test_get_market_cap_pit_returns_value():
    from src.tools.api import get_market_cap
    mc = get_market_cap("AAPL", "2024-06-30")
    assert mc is not None
    # Apple was ~3T at that time; allow wide bounds
    assert 1e12 < mc < 1e13
```

- [ ] **Step 16.3: Run the smoke test (manual, optional)**

Run: `pytest tests/integration/test_yfinance_smoke.py -m live -v`
Expected: 3 PASS (~30 seconds, requires network + SEC_EDGAR_USER_AGENT).

If running offline / in CI without env, the test auto-skips.

- [ ] **Step 16.4: Run full test suite (excluding live)**

Run: `pytest -m "not live" -v`
Expected: All previous tests + new unit tests PASS. No live test runs.

- [ ] **Step 16.5: Commit**

```bash
git add tests/integration/ pyproject.toml
git commit -m "test: add yfinance provider smoke test (marked live)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Final verification

**Files:** none

- [ ] **Step 17.1: Verify FD mode unchanged**

Run with no `DATA_PROVIDER` set:
```bash
pytest tests/test_cache.py tests/test_api_rate_limiting.py tests/backtesting/ -v
```
Expected: All previously-passing tests still PASS.

- [ ] **Step 17.2: Verify yfinance unit tests all green**

Run:
```bash
pytest tests/providers/ -v
```
Expected: All PASS.

- [ ] **Step 17.3: Run a small backtester smoke (optional, manual)**

If you have AWS Bedrock + SEC_EDGAR_USER_AGENT set, try:
```bash
DATA_PROVIDER=yfinance poetry run python src/main.py \
  --tickers AAPL --start-date 2024-01-01 --end-date 2024-03-31 \
  --analysts warren_buffett --model jp.anthropic.claude-opus-4-7
```
Expected: Process completes, prints a trading decision for AAPL, banner shows `Using data provider: yfinance ...`.

- [ ] **Step 17.4: Final commit (if any tweaks needed)**

If everything green, no commit needed. Otherwise fix and commit.

---

## Self-Review

### Spec coverage check
- [x] §1 Goals — all 5 covered (DATA_PROVIDER switch, zero agent change, PIT, signal recovery, default unchanged)
- [x] §2 Non-goals — v2 untouched, no validation framework, no per-function switches
- [x] §3 Architecture — 11 new files match the file structure listed
- [x] §4 Six entries — Task 15 wires all 6 with 4-line branches
- [x] §5.1 yfinance_source — Tasks 4, 5
- [x] §5.2 alpha_vantage — Task 8
- [x] §5.3 sec_edgar — Tasks 6, 7
- [x] §5.4 bedrock_sentiment — Task 9
- [x] §5.5 derived (TTM, PIT, market cap, metrics) — Tasks 10, 11, 12, 13
- [x] §6 SQLite cache — Task 2
- [x] §7 Rate limiting — embedded in alpha_vantage.py, sec_edgar.py
- [x] §8 Error handling — every fetcher returns empty/None on failure (no business exceptions)
- [x] §9 Configuration — Task 1 (Config) + Task 0 (.env.example)
- [x] §10 Compatibility & rollback — Task 15 preserves FD path; Task 17 verifies
- [x] §11 Testing — Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
- [x] §12 14 key decisions — all reflected in tasks
- [x] §13 YAGNI — no out-of-scope items added

### Placeholder scan
- No "TBD" / "TODO" / "implement later" anywhere
- All test bodies contain actual assertions
- All implementation steps include full code
- No "similar to Task N" without repetition

### Type consistency
- `safe_div` signature consistent across Tasks 11, 12, 13
- `compose_ttm`, `filter_pit`, `compute_metrics`, `compute_market_cap_pit` all match across tests and impl
- `Price`, `FinancialMetrics`, `LineItem`, `InsiderTrade`, `CompanyNews` field names match Pydantic model in `src/data/models.py`
- `Cache.get` / `Cache.set` signatures consistent
- `_invoke_haiku` / `annotate` consistent across Task 9 test and impl
- `parse_form4_xml(xml_text, ticker, filing_date)` consistent
- `dispatch.fetch_*` signatures consistent across Task 14 (definition) and Task 15 (call sites)

Plan complete.
