# Security proxy registry and read-only observation

`config/security_proxy_registry_v1.json` is a versioned product registry of
approved fallback observations. It is **default-disabled** and every path has
`official_board_preferred=true`, `fallback_only=true` and
`production_enabled=false`.

The registry contains eleven approved fallback paths and two explicit gaps:
`glass_substrate` and `catering` have `no_reliable_security_proxy` and never
issue Tencent requests. Every observation always carries this disclosure:

> 代理观察仅用于正式板块源不可用时的人工研究参考；不替代正式板块，不构成合成板块指数或投资建议。

`SecurityProxyObservationService` is explicitly invoked and only returns
individual ETF/leader security quotes. It writes no database rows, snapshots,
reports or Provider health records; it is not connected to Scheduler, API, UI,
the candidate chain or the official market-path registry. It does not calculate
an aggregate, weighted return, synthetic market return or artificial index.

For an isolated diagnostic run during market hours:

```bash
PYTHONPATH=backend python3.12 scripts/validate_security_proxy_observation.py --enable-provider
```

The default paths are `cpo`, `rare_earth` and `liquid_cooling`. The CLI makes
one deduplicated Tencent complete-security batch, with no retry, and writes
only parsed/desensitized JSON, CSV and Markdown to the ignored
`var/provider-research/security-proxy-observation/` directory.
