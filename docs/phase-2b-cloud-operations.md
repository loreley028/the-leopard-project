# Phase 2B-0 cloud daily operations

The normal daily report path is: Admin signs in, uploads the final PDF, then
the application performs deterministic local extraction, strict validation and
automatic publication. Any warning, date conflict or frozen-history conflict
stops before publication; the current published report and frozen ledger remain
unchanged.

## Post-close captures

`deployment/scripts/run_daily_market_capture.sh` is deliberately a short host
wrapper. It calls the two existing explicit CLI commands inside `leopard-api`:

1. `capture_live_market_anchor_daily.py` for `sh000001`.
2. `capture_security_proxy_daily.py` for the fixed proxy registry.

Install the two `deployment/systemd/leopard-daily-market-capture.*` templates
only during a release deployment, then run `systemctl daemon-reload` and
`systemctl enable --now leopard-daily-market-capture.timer`. The timer is
weekday 15:20 Asia/Shanghai with `Persistent=true`. The capture CLIs retain the
controlled calendar, post-close, no-overwrite and idempotency gates; the
legacy in-process market automation must remain disabled; systemd
does not retry failed Provider calls. Inspect outcomes with
`journalctl -u leopard-daily-market-capture.service`.

## HTTPS gate

`deployment/nginx/leopard-public-https.conf` is a template, not an installer.
Before any public cutover, confirm a production domain, DNS resolution and a
valid certificate. Until then leave the application on loopback and report
`public_cutover_https_prerequisite`. The template redirects port 80 to HTTPS,
keeps Docker's API port private, and applies `X-Robots-Tag: noindex, nofollow`
to HTML and PDF responses. This is a crawler directive, not access control.

## Backup and rollback

Before a release, run the existing `/opt/the-leopard-project/deployment/backup.sh`
to create a SQLite-consistent database and persistent-file backup. Record the
old `current` symlink. Release deployment builds and smoke-tests the candidate
before atomically moving `current`; rollback restores the previous release
pointer and containers. The Phase 2B schema is additive and requires no
destructive database rollback.
