# Security proxy EOD history import

`scripts/import_security_proxy_eod_history.py` accepts a user-approved CSV or
JSON source reference. The user confirms the source name, source reference and
that the input is explicitly unadjusted. Row-level manual verification is not
required.

The importer deterministically validates approved symbols, controlled trading
dates, future dates, duplicates, finite OHLC values, OHLC relationships,
unadjusted price mode and optional `amount_yuan`. It rejects a severe error for
the whole input and never calls a historical network provider or writes formal
SQLite. Existing daily files, including the 2026-08-05 Tencent EOD file, are
not overwritten without explicit research-only override.

An empty generated template is a schema aid only. It has no source metadata or
prices, cannot pass dry-run validation and must never be treated as history.
When no trusted input file has been supplied, the status is
`history_source_not_provided`; this does not require manually filling or
checking rows one at a time. It is not a launch blocker for a configuration-
curated ETF, a valid next-day selection snapshot, or Viewer observation.
History is accumulated naturally by the explicit EOD capture and only
enhances stock-level 20-day rebound and latest-turnover selection metrics; it
does not rank or replace curated ETFs.
