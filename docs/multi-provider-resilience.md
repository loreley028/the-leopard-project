# Multi-provider resilience — Phase 2A-0 cloud readiness

Status: framework complete; live coverage incomplete; **DO NOT MERGE**.

## Why this exists

On 2026-07-30 the Eastmoney board endpoint returned a connection-level empty reply while DNS and TLS still worked. The previous runtime therefore had no usable current quote for 62 of 65 supported sectors. This document records the fail-closed replacement architecture; it does not approve a production Provider.

## Capability evidence

`config/provider_capability_matrix_v1.json` contains exactly 65 supported canonical sectors and excludes `hang_seng_tech`. It never searches by approximate name at runtime. A candidate is selectable only when its exact mapping, spot endpoint and same-symbol daily history were all validated.

Controlled research was deliberately stopped after the upstream began returning HTTP 401:

| Result | Count |
|---|---:|
| validated direct | 47 |
| validated proxy | 0 |
| validated composite | 0 |
| unverified | 18 |
| no mapping | 0 |
| total | 65 |

The initial representative set passed 10/10. The bounded full scan validated 44 symbols before rate limiting; the separately recorded representative evidence also validates 电力 `881145`, 煤炭 `881105` and 贵金属 `881169`, producing the 47 total. No request retry loop, identity switching, Cookie, login, browser bypass or raw-response fixture was used.

The 18 unverified sectors stay out of the runnable chain. This includes the hotel/catering proxy and the three custom composites because their components were not reached before the bounded scan stopped. Their established business semantics remain unchanged; `unverified` is a technical admission result, not a mapping rewrite.

## Runtime selection

For each sector, the runtime reads a versioned ordered candidate list:

1. only `validation_status=validated` candidates are eligible;
2. candidates are tried by explicit priority;
3. an open Provider circuit is skipped;
4. the current quote and exactly four previous complete closes must come from the same Provider and symbol;
5. an incomplete candidate fails as a unit before the next validated candidate is considered;
6. no candidate means `no_valid_fallback`; all failed candidates mean `all_providers_unavailable`;
7. zero values, old EOD substitution, fuzzy names and cross-Provider MA5 are forbidden.

Snapshot lineage records the canonical sector, selected Provider and symbol, mapping type, priority, primary skip reason, fallback flag, spot/history sources, current timestamp and historical dates. Proxy and composite semantics remain explicit.

## Circuit breaker and request-storm prevention

Health is stored in `provider_health_records` per Provider and endpoint family. State survives an API restart and contains only a short error class and bounded summary—never a response, Cookie, token or request header.

The configured state machine is:

- `closed`: normal candidate requests; two consecutive failures open the circuit;
- `open`: no requests before `next_probe_at`;
- `half_open`: after cooldown, only a controlled representative probe is allowed;
- two recovery successes close the circuit;
- a half-open failure reopens it, with cooldown capped at two hours.

Within one scheduler cycle, the first request failure marks that Provider unavailable for the rest of the cycle. This stricter cycle-local guard prevents a connection failure from becoming a 62-sector request storm even before the persistent failure threshold is reached.

Admin can inspect state and request one real health probe. The endpoint refuses a probe while cooldown is active and provides no operation that directly writes `healthy`. Viewer routes never expose a mutation and never call the Provider or health probe.

## EOD and data-lane boundaries

The circuit and candidate chain apply to intraday snapshots and Provider-native MA5 history. Existing `complete_eod`, `pending_publication`, delayed gap-only retry, WAL/write coordination and immutable report snapshots are unchanged. A fallback does not overwrite prior `complete_eod`; intraday values never enter formal indicators or frozen reports. HSTECH stays unsupported and creates zero requests.

## Current release gate

The framework is deterministic and offline-testable, but the selectable capability count is 47/65. Therefore normal scheduler Stage C and the two-cycle Stage D acceptance were not run. Current live acceptance remains below 65/65, and PR #6 must remain Draft with `DO NOT MERGE`.

Next research must resume only after the upstream cooldown, validate the remaining exact THS symbols or a legally usable independent Provider, and then perform two normal five-minute scheduler cycles, 65/65 same-source MA5, Viewer zero-call verification, formal-data regression and CI.
