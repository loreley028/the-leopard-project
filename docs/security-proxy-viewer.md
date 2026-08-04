# Security proxy Viewer exposure

The Viewer always asks the backend to decide official-board availability. A
fresh official board snapshot produces `viewer_source_mode=official_board` and
does not request Tencent. Only unavailable, failed, missing or stale official
data can produce `viewer_source_mode=security_proxy`, and only for an approved
registry path.

The feature flag is `SECURITY_PROXY_VIEWER_ENABLED=false` by default. When
enabled, server-side cache entries live for 300 seconds; total upstream failure
uses a 30-second error cache. The cache is process-local, single-flight and
preserves source `quote_datetime` rather than relabelling cache time as market
time. It has no background refresh thread.

The CPO fallback displays the communication ETF as **部分覆盖** plus the three
independent leader securities. It never calls the ETF a CPO ETF and never
computes a CPO proxy return. Glass substrate and catering display the explicit
empty state because no reliable security proxy exists.

> 代理证券用于观察主题相关标的表现，不代表官方板块指数或完整行业表现。

This Viewer feature writes no database rows, snapshots, reports or history,
does not connect to Scheduler, and does not expose a general security lookup.
Production activation still requires independent UX approval, security review,
feature-flag approval and a separately deployed release.
