# System support scope v1

## Fixed counts

| Measure | Count |
|---|---:|
| Business catalog | 66 |
| Automatic A-share support | 65 |
| Unsupported | 1 |
| Daily collection denominator | 65 |

The denominator is a product-support denominator. If 64 supported sectors are collected, success is `64/65`, never `64/66`.

## Hang Seng Tech

| Field | Value |
|---|---|
| sector_name | 恒生科技 |
| canonical_symbol | HSTECH |
| market | HK |
| support_status | unsupported |
| data_status | unsupported |
| reason_code | cross_market_not_integrated |
| display_text | 暂不支持 |
| display_detail | 港股跨市场行情暂未接入 |

This is not `fetch_failed`, `missing`, `stale`, `provider_error`, `pending_retry`, or `abnormal`. HSTECH is excluded from automatic collection, indicators, rankings, liquidity statistics, alerts, retries, freshness monitoring, Provider success statistics, dual-source reconciliation, and the production coverage denominator.

Phase 1A proved that an HSTECH market-data basis could technically be obtained. That historical result remains unchanged. Phase 1B-0 makes the separate first-release product decision not to integrate cross-market automation.

## PDF boundary

The daily PDF remains driven by the live transcript and V2.3 PDF specification. If the host discusses Hang Seng Tech, the summary and path judgment remain. Automatic market-data support is not a prerequisite and must never delete transcript material. No PDF specification or business logic is changed in Phase 1B-0.
