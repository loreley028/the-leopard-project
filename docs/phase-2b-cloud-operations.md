# Phase 2B-0 cloud daily operations

The normal daily report path is: Admin signs in, uploads the final PDF, then
the application performs deterministic local extraction, strict validation and
automatic publication. Any warning, date conflict or frozen-history conflict
stops before publication; the current published report and frozen ledger remain
unchanged.

## Post-close captures

`deployment/scripts/run_daily_market_capture.sh` is a short host wrapper for
`advance_market_core.py --mode advance`. At 15:20 on controlled trading days
it first uses Tencent standard quotes for the registry-derived Market Core
universe, then checks exact-date coverage. Only symbols still missing that
exact completed day are repaired sequentially through Sina history. Neither
path reads Reports or PDFs.

Install the `leopard-daily-market-capture.*` templates together with
`leopard-market-freshness-reconcile.*`, then run `systemctl daemon-reload` and
enable both timers. The primary advance runs weekdays at 15:20; reconciliation
runs at 15:40 and 09:10 Asia/Shanghai. All timers use `Persistent=true`.
The reconciliation does not re-capture a complete universe: it reads SQLite
first and only requests missing exact-date symbols. HTTP 456 stops the current
Sina pass without retry or overwrite; the next scheduled reconciliation may
attempt the remaining gap. Inspect outcomes with `journalctl -u
leopard-daily-market-capture.service` and `journalctl -u
leopard-market-freshness-reconcile.service`.

## HTTPS gate

`deployment/nginx/leopard-public-https.conf` is a template, not an installer.
Before any public cutover, confirm a production domain, DNS resolution and a
valid certificate. Until then leave the application on loopback and report
`public_cutover_https_prerequisite`. The template redirects port 80 to HTTPS,
keeps Docker's API port private, and applies `X-Robots-Tag: noindex, nofollow`
to HTML and PDF responses. This is a crawler directive, not access control.

## Temporary IP subpath reader

If a domain is not ready, `deployment/nginx/leopard-public-ip-subpath.conf`
is the separate, temporary HTTP-only site template for
`http://47.116.209.204/leopard/`. It never redirects or proxies the IP root
into Leopard and is not an Nginx `default_server`, so other server sites keep
their own roots and host names. Build the web image with
`VITE_APP_BASE_PATH=/leopard/` before installing the template; this makes the
React router, assets, API calls, PDF downloads and preview images use the
same public namespace. Nginx strips that prefix only while proxying to the
loopback web container.

Use the versioned `deployment/Dockerfile.web` rather than a host-local
Dockerfile. Its `VITE_APP_BASE_PATH` build argument defaults to `/`; the
temporary IP release must explicitly build with `/leopard/`. The container's
versioned `deployment/nginx/leopard-web.conf` retains the SPA deep-link
fallback after the external proxy has removed that public prefix. It also
accepts `/leopard/` internally, so an SSH tunnel to `127.0.0.1:8080` can still
use the existing Admin route without exposing Admin over public HTTP.

On a server with no existing port-80 default site, install the separate
`deployment/nginx/temporary-ip-default-404.conf` first. It is a neutral
`default_server` that returns 404 for `/`; it prevents the Leopard IP vhost
from becoming the implicit default. If another project already owns the
default server, leave that existing site untouched and do not install a
second default server.

The temporary template denies `/leopard/admin`, the admin API namespace, the
admin-login API and every non-GET/HEAD public API request. Admin therefore
remains tunnel-only at `127.0.0.1:8080/admin/login` until a real HTTPS domain
is available. It applies `X-Robots-Tag: noindex, nofollow`, `nosniff` and a
conservative referrer policy only to this IP virtual host. `/leopard/robots.txt`
is served from the application's existing no-crawl asset; do not change a
root site's own `robots.txt` for this temporary mount.

## Backup and rollback

Before a release, run the existing `/opt/the-leopard-project/deployment/backup.sh`
to create a SQLite-consistent database and persistent-file backup. Record the
old `current` symlink. Release deployment builds and smoke-tests the candidate
before atomically moving `current`; rollback restores the previous release
pointer and containers. The Phase 2B schema is additive and requires no
destructive database rollback.
