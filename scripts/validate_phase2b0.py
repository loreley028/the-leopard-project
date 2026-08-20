"""Static Phase 2B-0 deployment-contract validation; no network or Provider access."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(path: Path, fragments: tuple[str, ...]) -> int:
    text = path.read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise SystemExit(f"{path.relative_to(ROOT)} missing: {', '.join(missing)}")
    return len(fragments)


def main() -> None:
    checks = 0
    checks += require(ROOT / ".env.example", (
        "LEOPARD_MARKET_AUTOMATION_ENABLED=false",
        "LEOPARD_AUTO_PUBLISH_UPLOADS=true",
    ))
    checks += require(ROOT / "deployment/scripts/run_daily_market_capture.sh", (
        "set -euo pipefail",
        "advance_market_core.py",
        "--mode advance",
        "--enable-tencent-provider",
        "--enable-sina-provider",
        "docker exec",
    ))
    checks += require(ROOT / "deployment/systemd/leopard-daily-market-capture.timer", (
        "OnCalendar=Mon..Fri *-*-* 15:20:00 Asia/Shanghai",
        "Persistent=true",
    ))
    checks += require(ROOT / "deployment/systemd/leopard-daily-market-capture.service", (
        "Type=oneshot",
        "run_daily_market_capture.sh",
        "TimeoutStartSec=300",
    ))
    checks += require(ROOT / "deployment/scripts/run_market_freshness_reconcile.sh", (
        "advance_market_core.py",
        "--mode reconcile",
        "--enable-sina-provider",
    ))
    checks += require(ROOT / "deployment/systemd/leopard-market-freshness-reconcile.timer", (
        "09:10:00 Asia/Shanghai",
        "15:40:00 Asia/Shanghai",
        "Persistent=true",
    ))
    checks += require(ROOT / "deployment/systemd/leopard-market-freshness-reconcile.service", (
        "Type=oneshot",
        "run_market_freshness_reconcile.sh",
        "TimeoutStartSec=300",
    ))
    checks += require(ROOT / "deployment/nginx/leopard-public-https.conf", (
        "listen 80;",
        "listen 443 ssl http2;",
        'X-Robots-Tag "noindex, nofollow"',
        "proxy_pass http://127.0.0.1:8080",
    ))
    checks += require(ROOT / "deployment/nginx/leopard-public-ip-subpath.conf", (
        "server_name 47.116.209.204",
        "location = /leopard",
        "location ^~ /leopard/",
        "location ^~ /leopard/api/v1/admin/",
        "X-Forwarded-Prefix /leopard",
        'X-Robots-Tag "noindex, nofollow"',
        "proxy_pass http://127.0.0.1:8080",
    ))
    checks += require(ROOT / "deployment/nginx/temporary-ip-default-404.conf", (
        "listen 80 default_server",
        "return 404",
    ))
    checks += require(ROOT / "deployment/Dockerfile.web", (
        "ARG VITE_APP_BASE_PATH=/",
        "ENV VITE_APP_BASE_PATH=${VITE_APP_BASE_PATH}",
        "deployment/nginx/leopard-web.conf",
    ))
    checks += require(ROOT / "deployment/nginx/leopard-web.conf", (
        "listen 8080",
        "location /api/",
        "location ^~ /leopard/api/",
        "location ^~ /leopard/",
        "try_files $uri $uri/ /index.html",
    ))
    checks += require(ROOT / "backend/leopard_project/web/app.py", (
        "auto_publish_uploads",
        "/api/v1/admin/operations/status",
        "publish_strict",
    ))
    checks += require(ROOT / "backend/leopard_project/web/services.py", (
        'storage_name = f".staging/{uuid4().hex}.pdf"',
        "def _promote_staged_pdf",
        "def reject_same_date_conflict",
    ))
    print(f"Phase 2B-0 deployment contract: {checks} checks passed")


if __name__ == "__main__":
    main()
