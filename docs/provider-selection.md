# Provider selection — Phase 1B-0

## Decision

Selected conclusion: **D — current free/public sources are not sufficient for stable production; the user must later decide whether to procure or authorize a production source.**

No source is approved as `production_primary` or `production_fallback`.

## Controlled 65-sector scan

The public THS diagnostic adapter was run sequentially with no automatic retries and a minimum 0.35-second interval:

- real data: 65/65;
- at least 120 sessions: 64/65;
- OHLC, pre_close, pct_change, volume and amount: 65/65;
- turnover_rate: 0/65;
- independently verified names: 0/65 because the chart callback does not expose names;
- cutoff distribution: 62 sectors ended 2026-07-21 while 3 exposed 2026-07-22 intraday records;
- glass substrate `886111`: 14 sessions, still a valid short-history mapping.

Coverage proves technical reachability, not production fitness. The callback is undocumented, lacks a project SLA and confirmed licensing, cannot independently verify names, omits turnover rate, and showed mixed cutoff timing. It remains `diagnostic_provider`.

## Candidate assessment

- **Public THS adapter:** useful for diagnosis and research fixtures; not promotable solely because it returned 65/65.
- **AKShare THS interfaces:** worth keeping as `research_provider` for interface comparison, but likely share the same or similar upstream and therefore do not establish an independent fallback. AKShare also documents Eastmoney sector interfaces, but adopting another taxonomy would require explicit mapping research rather than silent substitution. See the [official AKShare repository](https://github.com/akfamily/akshare) and [official interface inventory](https://github.com/akfamily/akshare/blob/main/docs/tutorial.md).
- **Tushare `ths_daily`:** remains `candidate_primary` only. Its official documentation describes OHLC, pre_close, pct_change, volume and turnover_rate, requires account permissions/points, and does not document amount. Phase 1B-0 neither requests credentials nor implements it. See [official Tushare documentation](https://tushare.pro/document/2?doc_id=260).

## Next decision gate

Phase 1B-1 should not start production ingestion. It may validate a second independent source, clarify licensing/SLA, establish name and unit contracts, and define a user decision between authorized procurement and continuing research.
