# Phase 1B-1 acceptance

## Support and EOD result

- Support remains 66/65/1 with denominator 65.
- HSTECH remains unsupported and creates zero EOD or reconciliation work.
- The 16:30 policy blocks the three observed 2026-07-22 intraday rows.
- The calendar abstraction handles controlled weekends, holidays, replay and injected time, but is not production-complete.

## Provider result

AKShare and the current adapter are `shared_upstream`, proven from AKShare 1.18.64 source. No independent second source exists and no Provider is approved for production.

## Controlled replay

- Plan: 65
- Provider A metadata successes: 65
- Provider B successes: 0
- Provider B live execution: `blocked_by_dependency_network`
- complete EOD: 62
- intraday excluded: 3
- one source missing: 62
- matched / acceptable / material / source-not-independent numerical records: 0
- manual-review-required: 62
- stale / future: 0
- short history: 1
- proxy: 1

The replay uses immutable Phase 1B-0 metadata. It does not reconstruct prices or claim live numeric dual-source validation.

## Decision

Neither `candidate_primary` nor `production_primary` is newly approved. Phase 1B-2 five-day observation should not begin until an actually independent, legally usable second source and a production-grade CN_A calendar are available.
