# Tencent standard-security Provider foundation

This is a default-disabled, read-only diagnostic Provider for complete Tencent
standard-security records. It is deliberately outside the market-path registry,
Scheduler, Viewer and Admin UI. It is not a `production_primary` Provider.

## Frozen empirical field contract

| Normalized field | Complete response index |
|---|---:|
| name | 1 |
| symbol | 2 |
| current | 3 |
| pre_close | 4 |
| quote_datetime | 30 |
| change | 31 |
| pct_change | 32 |

The contract is based on same-record arithmetic, p35 composite first-price and
Tencent minute-last-price evidence. The compact `s_sh` / `s_sz` wire format is
not called or parsed. p78 is permanently ignored and never a fallback.

## Scope and safeguards

- Inputs are only complete `shXXXXXX` and `szXXXXXX` A-share, ETF or explicitly
  configured exchange-index symbols.
- The endpoint uses one deduplicated batch, at most 20 securities, with a
  timeout of no more than ten seconds and no automatic retry.
- It sends no Cookie, Token, Referer or special User-Agent, and retains only a
  payload SHA-256—not the complete upstream response.
- A failed record is classified independently and cannot contaminate valid
  records in its batch. Supported classifications include `empty_reply`,
  `remote_disconnected`, `timeout`, `decode_error`, `malformed_record`,
  `insufficient_fields`, `stale_quote` and `calculation_inconsistent`.
- No THS `88xxxx` board, Tencent industry/concept board, HK/US security,
  custom basket, minute or historical endpoint is in scope.

## Diagnostic CLI

The checked-in switch remains off. A network request therefore requires an
explicit operator action:

```bash
PYTHONPATH=backend python3.12 scripts/validate_tencent_standard_quote_provider.py --enable-network
```

It performs exactly one complete-format batch for five public default symbols,
without retry, and writes parsed/desensitized JSON, CSV and Markdown reports
under `var/provider-research/tencent-standard-security/`. It never records the
complete query URL or raw response body.
