# Security proxy curated ETF and dynamic stock policy

The manually maintained configuration is an eligibility boundary, not a daily
ranking order. It identifies thematic relevance, permitted proxy instruments,
instrument type, coverage, required instruments and exclusions.

- Each path may name at most one approved `curated_etf_symbol`. It is selected
  exactly as configured with the reason `curated_observation_etf`; it is a
  theme/scale/liquidity observation instrument, not a claim that the ETF is
  the largest, most liquid, best-performing, or a complete sector proxy.
  Curated ETF choice is not re-ranked daily by AUM, shares, turnover, return,
  market cap, or history. A path without a curated ETF simply has no forced
  ETF selection and can still show its approved stock observations.
- `curated_etf_note`, `curated_etf_reviewed_at`, `curated_etf_coverage`, and
  `curated_etf_replaceable` record the human review boundary. `eligible_etf_symbols`
  and the deprecated `preferred_etf_symbols` remain readable for migration,
  but they never cause automatic ETF selection.
- Eligible large-cap companies are ranked by verified market cap when present.
  Missing market-cap data retains up to two approved large-cap candidates and
  uses `approved_large_cap_candidate`; it never claims an unsupported rank.
- Required instruments are never displaced. Dynamic rebound and latest-turnover
  slots only supplement the approved set, are deduplicated, and never create a
  synthetic sector return or index.

Security-level history is an optional enhancement for the stock rebound and
latest-turnover slots only. `history_source_not_provided`,
`missing_verified_aum`, and partial liquidity history do not invalidate a
curated ETF, a selection snapshot, or Viewer reading. The snapshot is
calculated after close and is only effective from the next controlled trading
day. Viewer reads it without recomputing selection; an invalid or unavailable
snapshot falls back to the static approved registry. The fixed Viewer
disclaimer remains unchanged.
