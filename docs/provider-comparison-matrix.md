# Provider comparison matrix

The machine-readable matrix is `data/provider-selection/provider_comparison.json`. Unknown values are `null`, not inferred scores.

| Provider | Role | Verified coverage | Key strengths | Blocking reasons | Recommendation |
|---|---|---:|---|---|---|
| `ths_public_validation` | diagnostic_provider | 65/65 | Current mappings reachable; OHLC/volume/amount present | Undocumented endpoint, no SLA, licensing unconfirmed, no independent name check, turnover absent, mixed cutoff | B: remain diagnostic |
| `akshare_ths` | research_provider | not live-tested | Maintained open-source interface layer and documented sector interfaces | Not independent enough from public upstream, no project SLA, repository integration not validated | Research only |
| `tushare_ths_daily` | candidate_primary | not account-tested | Documented API; pre_close, pct_change, volume and turnover documented | Account/points required, 65 code conversion unverified, amount not documented | Candidate only |

The matrix contains all required field, freshness, rate-limit, authentication, licensing, stability, complexity, maintenance, recommendation, and blocking-reason columns. Conclusions use the Phase 1B-0 live scan or linked official documentation; no impression-based numerical scoring is used.
