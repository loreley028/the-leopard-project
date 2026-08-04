# Security proxy EOD selection

This foundation selects research-only proxy securities from a manually approved candidate pool after a complete trading-day close. It is not a formal board index, a synthetic index, a sector return, or investment advice.

## Boundaries

`config/security_proxy_registry_v1.json` remains the product approval boundary: it says which paths may use a security proxy at all. `config/security_proxy_candidate_pool_v1.json` is a separate, versioned list of the only ETFs and stocks allowed to compete for each approved path. The EOD selection is a dated output of that pool. It never searches the full A-share universe, performs name matching, or changes either configuration.

The service is explicit and read-only. It does not call Tencent or any other Provider, write SQLite, start a Scheduler, publish an observation, or change the existing Viewer. The current Viewer therefore continues to read the static proxy registry only.

## Objective rules

At most one ETF is selected from its path-local pool by the largest fresh `latest_aum`. AUM must be positive and has an explicit data date/source. It is never inferred from stock market cap or turnover. A stale AUM is marked `aum_stale`; only an already selected ETF may be retained as a stale previous result. Otherwise the result is `no_eligible_etf`.

Stocks compete only inside their manually approved path-local pool after a complete EOD date:

- `largest_market_cap`: largest end-of-day `total_market_cap`.
- `fastest_rebound`: largest `(close / rolling_low - 1) * 100`, where `rolling_low` is the lowest daily low across the latest 20 complete trading days.
- `highest_turnover`: largest same-day `amount`.

Missing, non-positive, incomplete, duplicate-date, future-dated, or non-EOD input does not get filled with zero and cannot compete for the affected slot. The initial tie break is metric value, then average amount, then total market cap, then symbol order.

One stock may lead more than one slot but is shown once with all of its selection reasons. The service then walks the same slot ranking to fill a vacant display place from the next eligible candidate. It never reaches outside the candidate pool.

## Manual policy

`manual` uses only required stocks; `hybrid` emits required stocks first and fills remaining places from the configured objective slots; `auto` has no required stocks. Required instruments are immutable for that selection, consume a leader place, and show `manual_required` with the reason `固定核心观察`. Excluded instruments remain excluded even if their metrics rank first.

- CPO keeps exactly 中际旭创 (`sz300308`), 新易盛 (`sz300502`), and 天孚通信 (`sz300394`) as fixed core leaders. Its ETF remains separately eligible by AUM.
- 创新药/医药 keeps 药明康德 (`sh603259`) and 迈瑞医疗 (`sz300760`) as fixed core leaders. It may add at most one approved automatic candidate; the broad observation definition is intentional.

There is no aggregate proxy percentage change, weighted return, average return, or synthetic index.

## Research-only input contract and snapshot

Existing `complete_eod` rows are sector-level OHLC/amount records. They do not contain security-level total market cap or ETF AUM, so this foundation defines a separate research-only input contract: security symbol, trading date, complete EOD close/low/amount/total market cap, and ETF AUM/as-of/source. This phase does not connect an external source to fill these fields.

Run the deterministic offline demonstration with:

```bash
PYTHONPATH=backend .venv/bin/python3.12 scripts/generate_security_proxy_eod_selection.py
```

It writes ignored, auditable files below `var/provider-research/security-proxy-eod-selection/`: `selection.json`, `selection.csv`, `selection.md`, `comparison-with-previous.json`, and `summary.json`. Passing `--input path.json` supplies an explicit research-only EOD input instead. The CLI does not make network requests.

## Before later integration

A later phase would need an approved security-level EOD source for close, low, amount, total market cap, and ETF AUM; formal data-quality checks; a reviewed persistence design; controlled post-close scheduling; Viewer policy review; privacy and license review; and end-to-end tests. None is enabled here.
