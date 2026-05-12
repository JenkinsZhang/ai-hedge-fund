# Spec: yfinance Data Provider with PIT-Strict Free-Source Stack

> **Date**: 2026-05-12
> **Status**: Approved (brainstorming complete, ready for implementation plan)
> **Scope**: Replace Financial Datasets API with a free-source stack (yfinance + Alpha Vantage + SEC EDGAR + Bedrock Haiku) without changing any agent, workflow, prompt, or data structure.

---

## 1. Goals

1. **Allow swap to free data sources** via a single env var: `DATA_PROVIDER=yfinance`
2. **Zero changes** to:
   - Agent code (`src/agents/*.py`)
   - Pydantic data models (`src/data/models.py`)
   - The 6 public API function signatures (`src/tools/api.py`)
   - LangGraph workflow / prompt templates / risk & portfolio managers
3. **Strict point-in-time (PIT) correctness** — must never expose future data
4. **Restore signal quality** for sentiment-dependent and insider-dependent agents
5. **Default behaviour unchanged**: `DATA_PROVIDER` unset → identical to current code path

## 2. Non-Goals

- Replace v2/event_study or v2/data — they remain Financial Datasets only
- Cross-source validation framework, data-quality dashboard, mutation testing
- Per-function provider switches (only a single global switch)
- Hot-swap providers at runtime (env-based static selection only)

## 3. Architecture

### 3.1 High-level flow

```
agent (warren_buffett.py, etc.)              ← unchanged
        │
        ▼
src/tools/api.py                              ← only the 6 function bodies gain a 4-line if-branch
        │
        ├─ DATA_PROVIDER=financial_datasets (default) → original code path, byte-for-byte
        │
        └─ DATA_PROVIDER=yfinance → src.tools.providers.dispatch.fetch_*
                                          │
                                          ▼
                                    Provider sources + Derived layer
                                          │
                                          ▼
                                    SQLite cache + HTTP retry layer
```

### 3.2 New file layout (under `src/tools/providers/`)

```
providers/
├── __init__.py              # public surface (re-exports dispatch.fetch_*)
├── _http.py                 # shared requests Session + 429 retry + rate limiting
├── _cache.py                # SQLite persistent cache (pickle-encoded payloads)
├── _config.py               # env var loading + startup validation
├── yfinance_source.py       # prices, three-statement reports, quarterly shares
├── alpha_vantage.py         # NEWS_SENTIMENT (primary), INSIDER_TRANSACTIONS (fallback)
├── sec_edgar.py             # CIK resolver, submissions JSON, Form 4 XML parser
├── bedrock_sentiment.py     # Haiku 4.5 sentiment annotator (uses existing get_model)
├── derived.py               # PIT market_cap, TTM composer, ratio computations
└── dispatch.py              # 6 dispatcher functions, hard-coded fallback chains
```

11 files. No class hierarchies, no decorators, no plugin registry.

### 3.3 Abstraction policy

- **Single Protocol** (`DataProvider`) — duck-typed, capability-detected via `hasattr`
- **No ABC, no NotImplementedError raisers**
- **Sources do not import sources** — shared logic lives in `derived.py` or `_http.py`
- **`ProviderResult` metadata** (source, as_of_date, is_pit, quality, warnings) is internal only — never crosses the `dispatch.py` boundary back into agents
- **Each source file ≤ ~200 lines**; if it grows beyond, split by concern

## 4. The 6 Public Entry Points (unchanged signatures)

All in `src/tools/api.py`. Each function gets a 4-line top-of-body branch:

```python
def get_prices(ticker, start_date, end_date, api_key=None) -> list[Price]:
    if os.getenv("DATA_PROVIDER", "financial_datasets") == "yfinance":
        from src.tools.providers import dispatch
        return dispatch.fetch_prices(ticker, start_date, end_date)
    # ... original FD code preserved verbatim below ...
```

Function-level summary in `yfinance` mode:

| Entry | Source chain | Notes |
|---|---|---|
| `get_prices` | yfinance_source | Direct OHLCV |
| `search_line_items` | yfinance_source | Three-statement field mapping (22+ already mapped) |
| `get_financial_metrics` | derived (built from yfinance + SEC shares) | All 41 fields self-computed |
| `get_market_cap` | derived (close × shares_outstanding, PIT) | Never uses `Ticker.info["marketCap"]` |
| `get_company_news` | alpha_vantage → yfinance_source + bedrock_sentiment | AV primary; AV cache before 5-RPM hit |
| `get_insider_trades` | sec_edgar → alpha_vantage (fallback) | SEC Form 4 official source |

## 5. Provider Behaviour Details

### 5.1 yfinance_source.py

- Uses `yfinance.Ticker(symbol)` with `auto_adjust=False` for prices
- Three statements via `quarterly_income_stmt`, `quarterly_balance_sheet`, `quarterly_cashflow`, plus annual variants
- Field mapping uses the existing `LINE_ITEM_CANDIDATES` pattern (multi-name fallback for Yahoo schema drift)
- **Forbidden**: `Ticker.info["marketCap"]`, `Ticker.info["sharesOutstanding"]` — current values, would create lookahead bias

### 5.2 alpha_vantage.py

- Endpoints used: `NEWS_SENTIMENT`, `INSIDER_TRANSACTIONS`
- Detects rate-limit response (`"Note: Thank you for using Alpha Vantage"` or HTTP 429) → returns `None` to signal fallback
- `time.sleep(12)` only when actually issuing HTTP (cache hits skip)
- API key from `ALPHAVANTAGE_API_KEY` env

### 5.3 sec_edgar.py

- CIK resolver: pull `https://www.sec.gov/files/company_tickers.json` once, cache 30 days
- Submissions: `https://data.sec.gov/submissions/CIK<10-digit>.json` — gives filing index
- Form 4 XML: `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<doc>.xml`
- Parses `nonDerivativeTransaction` blocks; ignores derivative transactions for now
- **Required**: `SEC_EDGAR_USER_AGENT` env (format: `name email`). Missing → startup `ValueError`
- Rate limit: `time.sleep(0.11)` (≈9 RPS)

### 5.4 bedrock_sentiment.py

- Reuses `src.llm.models.get_model("us.anthropic.claude-haiku-4-5", ModelProvider.BEDROCK)`
- Batches news titles, returns `bullish | bearish | neutral` per title
- Cache key = `hash(title)` → permanent TTL (titles never re-classified)

### 5.5 derived.py

Three public functions:

```python
def build_ttm_line_items(ticker: str, end_date: str) -> LineItem | None
def compute_market_cap_pit(ticker: str, end_date: str) -> float | None
def compute_financial_metrics(ticker, end_date, period, limit) -> list[FinancialMetrics]
```

#### 5.5.1 PIT enforcement

For every quarterly report from yfinance:
1. Look up `filing_date` from SEC submissions (cached 7 days)
2. Drop the entire period if `filing_date > end_date`
3. If filing_date is unavailable (e.g. ADR / non-US ticker / CIK lookup fails) → **drop the period** (per user decision: never assume future)
4. Log WARN once per ticker

#### 5.5.2 TTM Composer

```python
FLOW_FIELDS  = {"revenue", "gross_profit", "operating_income", "net_income",
                "ebit", "ebitda", "interest_expense", "free_cash_flow",
                "capital_expenditure", "depreciation_and_amortization",
                "dividends_and_other_cash_distributions",
                "issuance_or_purchase_of_equity_shares"}

STOCK_FIELDS = {"total_assets", "current_assets", "cash_and_equivalents",
                "total_liabilities", "current_liabilities", "total_debt",
                "shareholders_equity", "outstanding_shares",
                "goodwill_and_intangible_assets"}
```

- Flow fields = sum of last 4 PIT-valid quarters
- Stock fields = latest PIT-valid quarter's BS value
- Average fields (denominators for ROE/ROA) = mean of current and 4-quarters-back BS
- Year-over-year growth = current TTM / 4-quarters-back TTM − 1

If fewer than 4 PIT-valid quarters available → return `None` (cascade to empty list at dispatch level).

#### 5.5.3 Market Cap PIT

```
market_cap(end_date) = close_price(t) × shares_outstanding(t)
                       where t = max(date <= end_date)
```

Shares source priority:
1. yfinance `quarterly_balance_sheet` `Ordinary Shares Number` / `Share Issued`
2. SEC `companyfacts` `dei:CommonStockSharesOutstanding`
3. None (caller falls through to `None`)

#### 5.5.4 41 FinancialMetrics fields

| Category | Strategy | Fields |
|---|---|---|
| Direct ratio | `safe_div(num, den)` | gross_margin, operating_margin, net_margin, roa, roe, roic, current_ratio, quick_ratio, cash_ratio, debt_to_equity, debt_to_assets, asset_turnover |
| Cross-period growth | `current_TTM / prev_year_TTM - 1` | revenue_growth, earnings_growth, fcf_growth, ebitda_growth, operating_income_growth, book_value_growth, eps_growth |
| Price-based | `market_cap / TTM_x` | pe_ratio, pb_ratio, ps_ratio, ev_ebitda, ev_revenue, peg_ratio, fcf_yield |
| Per-share | `TTM_x / shares` | eps, bvps, fcf_per_share |
| Coverage | `ebit / abs(interest_expense)` | interest_coverage |
| Liquidity | balance-sheet derived | operating_cash_flow_ratio |
| Cycle | from receivables/inventory/payables | DSO, inventory_turnover, receivables_turnover, working_capital_turnover, operating_cycle |

ROIC formula: `nopat / invested_capital`, where
- `nopat = ebit × (1 − effective_tax_rate)`, with effective tax rate fallback to 0.21 if not derivable
- `invested_capital = total_debt + shareholders_equity − cash_and_equivalents`

All fields use `safe_div` semantics: divide-by-zero or `None` operand → `None`. NaN/Inf → `None`.

**Partial fill rule**: if `market_cap` is `None`, only price-based fields become `None`; ratios derived purely from line items (margins, ROE, growth) still populate.

## 6. Caching

### 6.1 Storage

- File: `${PROVIDER_CACHE_DIR:-~/.cache/ai-hedge-fund}/providers.db`
- Single table:

```sql
CREATE TABLE cache (
    key         TEXT PRIMARY KEY,
    value       BLOB NOT NULL,         -- pickle.dumps(payload)
    fetched_at  INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL       -- 0 = forever
);
CREATE INDEX idx_fetched_at ON cache(fetched_at);
```

- `check_same_thread=False`, short transactions, single connection per process

### 6.2 Key format

```
<provider>:<fn>:<ticker>:<start>:<end>:<period>:v1
```

Examples:
- `yfinance:prices:AAPL:2024-01-01:2024-06-30:day:v1`
- `derived:financial_metrics:AAPL::2024-06-30:ttm:v1`
- `sec_edgar:form4:AAPL:2024-01-01:2024-06-30:v1`

`v1` is a global schema version — bump it to invalidate everything.

### 6.3 TTL policy

| Data | TTL |
|---|---|
| Prices, end_date < today−2 | 0 (forever) |
| Prices, recent | 5 minutes |
| Quarterly statements | 7 days |
| Annual statements | 30 days |
| SEC submissions / filing dates | 7 days |
| SEC Form 4 (end_date < today−2) | 0 (forever) |
| AV NEWS_SENTIMENT | 1 day |
| Bedrock annotations | 0 (forever, key = hash(title)) |
| Shares outstanding (quarterly) | 7 days |

## 7. Rate Limiting

| Source | Limit | Strategy |
|---|---|---|
| Alpha Vantage | 5 RPM (free tier) | `time.sleep(12)` per HTTP issue; 429 → fallback |
| SEC EDGAR | ~10 RPS | `time.sleep(0.11)` per request |
| yfinance | unofficial, soft | `time.sleep(0.5)` per request |
| Bedrock | per AWS account | none (existing setup) |

**Cache hits skip all sleep.**

## 8. Error Handling & Fallback

| Entry | Primary failure | Fallback | Final fallback |
|---|---|---|---|
| `get_prices` | yfinance empty | — | `[]` |
| `search_line_items` | yfinance empty | — | `[]` |
| `get_financial_metrics` | < 4 PIT quarters | — | `[]` |
| `get_market_cap` | shares missing | SEC companyfacts | `None` |
| `get_company_news` | AV 429/empty | yfinance + Bedrock | `[]` |
| `get_insider_trades` | SEC 4xx/5xx | AV INSIDER_TRANSACTIONS | `[]` |

**Never raise business exceptions.** Only configuration errors (missing `SEC_EDGAR_USER_AGENT`) raise — at startup, before any agent runs.

## 9. Configuration

### 9.1 New env vars (added to `.env.example`)

```bash
# Provider switch: financial_datasets (default) | yfinance
DATA_PROVIDER=financial_datasets

# Alpha Vantage — get a free key at https://www.alphavantage.co/support/#api-key
ALPHAVANTAGE_API_KEY=

# SEC EDGAR User-Agent (required when DATA_PROVIDER=yfinance)
# Format: "your-name your-email@example.com"
SEC_EDGAR_USER_AGENT=

# Optional: override cache directory
PROVIDER_CACHE_DIR=
```

### 9.2 New runtime dependency

`pyproject.toml`:
```toml
yfinance = "^0.2.50"
```

`requests`, `pydantic`, `boto3` (via langchain-aws), and `sqlite3` (stdlib) are already present.

### 9.3 Startup validation

`providers/_config.py` runs on first import (lazy from `dispatch.py`):

- Missing `SEC_EDGAR_USER_AGENT` → `ValueError` with clear message
- Missing `ALPHAVANTAGE_API_KEY` → WARN log (yfinance + Bedrock fallback still works)
- Missing `AWS_BEARER_TOKEN_BEDROCK` → WARN log (AV alone still works)

### 9.4 Startup banner

When `DATA_PROVIDER` is read, log INFO once:
```
Using data provider: yfinance  (alpha_vantage=enabled, sec_edgar=enabled, bedrock=enabled)
```

Or for default:
```
Using data provider: financial_datasets
```

This is mandatory per user requirement.

## 10. Compatibility & Rollback

| Scenario | Behaviour |
|---|---|
| `DATA_PROVIDER` unset | Default `financial_datasets`, original code path, byte-for-byte |
| `DATA_PROVIDER=financial_datasets` | Same as above |
| `DATA_PROVIDER=yfinance` | New path |
| `request.api_keys["FINANCIAL_DATASETS_API_KEY"]` injected | Honoured in FD mode, ignored in yfinance mode |
| CLI `python src/main.py` | Both modes work |
| CLI `python src/backtester.py` | Both modes work |
| Web `/hedge-fund/run` and `/hedge-fund/backtest` | Both modes work |
| `v2/event_study/`, `v2/data/FDClient` | Untouched, FD only |

**Rollback**: Single git revert restores FD-only mode. All changes localized to `src/tools/providers/` (new), `src/tools/api.py` (24 lines added), `pyproject.toml` (1 dep), `.env.example` (4 lines).

## 11. Testing

### 11.1 Unit tests (`tests/providers/`, mocked HTTP)

```
tests/providers/
├── test_dispatch_routing.py    # FD mode never imports providers
├── test_derived_ttm.py         # 4-quarter sum correctness
├── test_derived_pit.py         # future filing_date drops the period
├── test_derived_metrics.py     # 41 fields formula correctness
├── test_cache.py               # SQLite hit / miss / TTL expiration
├── test_sec_form4_parser.py    # one fixture XML round-trip
└── fixtures/
    └── sec_form4_apple.xml
```

Rules:
- Never issue real HTTP
- `monkeypatch` replaces `_http.py` session
- Pass on offline CI machines

### 11.2 Smoke integration test (live, manual)

```
tests/integration/
└── test_yfinance_smoke.py      # @pytest.mark.live
```

- Runs 1 ticker, 1 month, 1 agent (Buffett)
- `DATA_PROVIDER=yfinance` set in env
- Asserts: run completes, decisions dict non-empty, at least one non-neutral signal
- Marked `@pytest.mark.live` — CI default skips, run locally:
  `pytest tests/integration/test_yfinance_smoke.py -m live`

### 11.3 Coverage targets

| Module | Target |
|---|---|
| `dispatch.py` | 100% (small surface, all branches must be tested) |
| `derived.py` | ≥ 90% |
| Source files | ≥ 70% |
| `_http.py`, `_cache.py` | ≥ 80% |

## 12. Key Decisions Captured

| # | Decision | Rationale |
|---|---|---|
| 1 | Ambition: P0 + P1 only (yfinance + AV + SEC + Bedrock; skip Finnhub, validation framework) | Recovers signal quality without over-engineering |
| 2 | Single global env switch `DATA_PROVIDER` | Simplest UX; no per-function fragmentation |
| 3 | Strict filing_date PIT | Never expose future data, even if ADR loses coverage |
| 4 | Sentiment: AV primary + Bedrock fallback | Free tier first, paid token second; SQLite cache amplifies AV |
| 5 | Insider: SEC EDGAR primary, AV fallback | Official, complete; AV catches edge cases |
| 6 | Bedrock fallback reuses existing `get_model(...)` | Don't reimplement boto3 client logic |
| 7 | Cache hit skips sleep | Performance, no cost to do this |
| 8 | YoY growth uses 4-quarters-back, not 365-day-back | Aligns with reporting periods, avoids seasonal mismatch |
| 9 | Missing filing_date → drop the period | Never predict the future |
| 10 | Missing market_cap → partial fill | Margins/ROE still useful even without price-based fields |
| 11 | Cache path defaults to `~/.cache/ai-hedge-fund/`, override via `PROVIDER_CACHE_DIR` | Cross-project share, env override available |
| 12 | Mandatory startup banner | User explicitly required visible provider indicator |
| 13 | v2/ unchanged | Self-contained, FD-specific tooling |
| 14 | Tests minimal — main flow over coverage | User priority: main flow works |

## 13. Out of Scope (Explicit YAGNI list)

- Cross-source numerical reconciliation
- Data-quality dashboards / metric exporters
- Provider plugin registry / dynamic loading
- Per-function or per-ticker provider switches
- Property-based or mutation testing
- Auto-recovery of FD when yfinance fails (would defeat the point)
- v2/ module migration
- Finnhub provider (might add later if AV/SEC prove insufficient)

## 14. Open Risks

| Risk | Mitigation |
|---|---|
| Yahoo Finance schema drift | Multi-candidate field mapping; if all candidates miss, log WARN and return None |
| SEC EDGAR rate-limit policy change | Respect 10 RPS hard cap; honour their User-Agent requirement |
| Alpha Vantage free tier shrinks further | Bedrock Haiku fallback already in place |
| Bedrock token expiry mid-backtest | `provide_token()` auto-refresh via aws-bedrock-token-generator (already covered by user's existing setup) |
| yfinance package abandoned | Pinned to `^0.2.50`; can swap to alternative if needed |
| SQLite corruption on Windows | Single-process design; use `pragma journal_mode=WAL`; corrupt DB → recreate |

---

## Appendix A: File-by-file change summary

| File | Change |
|---|---|
| `pyproject.toml` | +1 dep (yfinance) |
| `.env.example` | +4 env vars |
| `src/tools/api.py` | +4 lines × 6 functions = +24 lines (no deletions) |
| `src/tools/providers/` (new dir) | 11 new files |
| `src/data/models.py` | unchanged |
| `src/data/cache.py` | unchanged |
| `src/agents/*.py` | unchanged |
| `src/utils/*.py` | unchanged |
| `src/llm/*.py` | unchanged (Bedrock provider already added in earlier work) |
| `app/backend/*` | unchanged |
| `app/frontend/*` | unchanged |
| `v2/*` | unchanged |
| `tests/providers/` (new) | 6 unit-test files + fixtures |
| `tests/integration/test_yfinance_smoke.py` (new) | 1 live smoke test |

## Appendix B: Lifecycle of a typical request

`get_financial_metrics("AAPL", "2024-06-30", period="ttm", limit=4)` in yfinance mode:

1. `api.py:get_financial_metrics` reads env, sees `yfinance`, delegates to `dispatch.fetch_financial_metrics`
2. `dispatch` checks SQLite cache (`derived:financial_metrics:AAPL::2024-06-30:ttm:4:v1`)
3. Miss → calls `derived.compute_financial_metrics`
4. `derived` calls `yfinance_source.fetch_quarterly_statements("AAPL")` (cached 7 days)
5. `derived` calls `sec_edgar.get_filing_dates(cik_for("AAPL"))` (cached 7 days)
6. Filter quarters where `filing_date > 2024-06-30` → drop
7. Sum last 4 PIT-valid quarters → TTM line items
8. Compute `market_cap_pit` via `compute_market_cap_pit("AAPL", "2024-06-30")`
9. Apply 41 ratio formulas, partial-fill where dependencies missing
10. Validate via Pydantic `FinancialMetrics(...)` — schema preserved
11. Store result in SQLite cache
12. Return `list[FinancialMetrics]` to agent — agent sees identical type as FD mode
