from pathlib import Path


def test_web_nginx_compresses_text_and_caches_only_fingerprinted_assets() -> None:
    config = (Path(__file__).parents[1] / "deployment/nginx/leopard-web.conf").read_text()

    assert "gzip on;" in config
    assert "application/javascript" in config
    assert "application/json" in config
    assert "location ^~ /assets/" in config
    assert "location ^~ /leopard/assets/" in config
    assert 'Cache-Control "public, max-age=31536000, immutable"' in config
    assert "location = /index.html" in config
    assert 'Cache-Control "no-cache"' in config
