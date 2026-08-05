# Security proxy automatic ranking policy

The manually maintained configuration is an eligibility boundary, not a daily
ranking order. It identifies thematic relevance, permitted proxy instruments,
instrument type, coverage, required instruments and exclusions.

- An eligible ETF is selected by verified AUM when available. Otherwise the
  service compares the median `amount_yuan` over 20 complete trading days.
  With five to nineteen days it may use the partial-history liquidity result;
  below five days it keeps the static approved ETF and records an explicit
  warning. Turnover is never described as AUM or fund size.
- Eligible large-cap companies are ranked by verified market cap when present.
  Missing market-cap data retains up to two approved large-cap candidates and
  uses `approved_large_cap_candidate`; it never claims an unsupported rank.
- Required instruments are never displaced. Dynamic rebound and latest-turnover
  slots only supplement the approved set, are deduplicated, and never create a
  synthetic sector return or index.

The snapshot is calculated after close and is only effective from the next
controlled trading day. Viewer reads it without recomputing the ranking; an
invalid or unavailable snapshot falls back to the static approved registry.
