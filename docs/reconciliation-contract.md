# Reconciliation contract

## Input and output

Each record stores the requested/actual dates, sector identity, Provider names and lineage references, EOD states, optional source values, absolute/percentage differences, missing fields, anomaly codes, status, and deterministic run identity.

Amount and turnover are never fabricated. Missing amount is recorded and may continue under `missing_optional_field_policy=record_and_continue`; missing close, pct_change, or volume produces `field_missing`.

## Status precedence

1. intraday and future snapshots block comparison;
2. stale/missing dates and Provider failure block comparison;
3. missing sources, calendar mismatch and required fields are explicit;
4. shared upstream becomes `source_not_independent`, even for identical values;
5. only independent, complete inputs can be classified as matched, acceptable, material, or manual review.

## Validation thresholds

| Threshold | Value |
|---|---:|
| close matched | 0.01% |
| close acceptable | 0.10% |
| pct_change matched | 0.01 percentage point |
| pct_change acceptable | 0.05 percentage point |
| volume acceptable | 1.00% |
| amount acceptable | 1.00% |
| manual review | close difference above 0.50% |

These are Phase 1B-1 validation thresholds, not production policy.
