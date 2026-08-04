# Tencent standard-security quote contract research

Status: **research only / ambiguous / not approved for production**

## Scope and legacy evidence

The legacy `option_monitor` project requests `http://qt.gtimg.cn/q={params}` with
`s_sh{code}` or `s_sz{code}` identifiers, comma-separated in one batch. Its parser
uses field 1 as name, field 2 as symbol and field 5 as percentage change. It adds
no Cookie, token, Referer or special User-Agent and refreshes every 30 seconds.
That behavior is evidence about the old application only; it is not a formal
Tencent API specification.

On 2026-08-04 during the A-share afternoon session, an isolated Alibaba Cloud
container made exactly two controlled calls, with no retry:

1. Compact: `s_sh510050,s_sh510300,s_sh588000,s_sz159901,s_sz159915`
2. Full: `sh510050,sh510300,sh588000,sz159901,sz159915`

Both returned HTTP 200, non-empty GBK content. Compact records contained 12
tilde-separated fields; full records contained 88. No full upstream response is
stored in Git.

## Inference gates and outcome

For each of the five securities, the analysis searched for positive current and
previous-close candidates, a percentage field agreeing with
`(current / pre_close - 1) × 100`, agreement with compact field 5 within 0.05
percentage point, and a 14-digit timestamp in the current trading session. A
contract was admissible only if the same indices worked for all five securities
and the tuple was unique.

| Field | Result |
|---|---:|
| name | index 1, unique |
| symbol | index 2, unique |
| current | unresolved |
| pre_close | unresolved |
| pct_change | unresolved |
| quote_datetime | index 30, unique |

Two common price tuples survived all numerical checks: `(3, 4, 32)` and
`(78, 4, 32)`. Because current has two equally valid positions under the allowed
evidence, choosing index 3 from a commonly circulated field table would violate
the required empirical uniqueness rule. The five securities therefore have no
accepted full-price parse and no accepted formula-validation result.

The frozen result is:

```text
tencent_standard_quote_transport_promising
tencent_quote_field_contract_ambiguous
```

## Follow-up semantic-anchor run (2026-08-04 14:17 CST)

This follow-up used one full batch, one compact batch and one same-day minute
request for each of `510300`, `300308` and `600111` (five requests total, no
retry). Every endpoint returned HTTP 200. The planned anchors deliberately do
not require an explanation for every field or a unique interpretation of p78.

| Security | p3/formula/p35/minute | p3 vs compact p3 | p31 vs compact p4 | Result |
|---|---|---|---|---|
| 510300 | pass | pass | pass | pass |
| 300308 | pass | fail: 0.12 difference | fail: 0.12 difference | fail closed |
| 600111 | pass | pass within tolerance | pass within tolerance | pass |

For `300308`, full p3 and p35 were both `1022.00`, and the Tencent minute last
price was also `1022.00`; the compact response, requested separately, showed
`1021.88`. The difference is larger than the configured display-precision
tolerance. It may reflect a real intra-request update, but this bounded run
cannot prove that, and no retry is permitted. Therefore p3 is not promoted.

p78 was distinct for the ETF and empty for both stocks; it is explicitly
observational and is neither a canonical current field nor a fallback. The
current status is `unresolved`, not a transport rejection.

The machine-readable contract is
`config/research/tencent_standard_quote_contract_v1.json`. Its price indices are
`null`, `production_approved` is false, and the research parser fails closed with
`tencent_quote_field_contract_unresolved`. It is not wired into the Provider
abstraction, Scheduler, Viewer, registry or deployment.

## Limits and next evidence needed

- Numeric equality cannot distinguish duplicate or derived fields.
- The test establishes transport reachability from one cloud egress, not SLA,
  license, continuity or production suitability.
- A future confirmation needs independent semantic evidence for the duplicated
  current field, such as an authoritative protocol specification or a controlled
  cross-state observation that makes the candidate fields diverge.
- Any further live probe requires a separate, explicitly bounded instruction.
