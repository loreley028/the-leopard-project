# Viewer and Admin boundary

Viewer报告库和增强报告只允许`published`；`needs_review`、草稿、撤回和解析失败均不得出现。Admin默认流程为PDF上传→本地解读→仅处理真实异常→确认发布，confirmed内容与完整66板块编辑器默认收起。

| Capability | Viewer | Admin |
|---|---:|---:|
| Read published reports and PDFs | yes | yes |
| Read sector opinions | yes | yes |
| See drafts, failures and unmapped terms | no | yes |
| Upload and parse PDF | no | yes |
| Confirm date and review fields | no | yes |
| Publish or withdraw | no | yes |
| View source page/range/evidence | no | yes |
| Refresh/import real-local market data | no | yes |
| Version specification backups | no | yes |

Authentication is enforced in FastAPI with a signed, HttpOnly, SameSite=Strict cookie. Passwords and the session secret come from environment variables. The frontend contains no password or permission decision. There is no registration, password recovery, email, SMS, OAuth or SSO.

This is not a production identity platform. Local accounts are deliberately limited and must not be exposed publicly.
## Current revision and daily Admin

Viewer receives only `published AND is_current` reports and never sees the Admin navigation. Admin sees every revision and manages a dynamically generated live-date schedule. Friday/Saturday default to “normally no report” and can be explicitly skipped, unskipped, or used for upload.

Viewer page rendering never triggers Provider or PDF-download access. Admin must explicitly request a lazy inline PDF preview, a diagnostic market refresh, an import confirmation or a specification-file download. Specification backups remain independent from report interpretation.

Viewer may read `/market/intraday/status` and `/market/intraday/sectors`, both backed only by server state/database cache. Only Admin may pause, resume or request an immediate intraday cycle. `real_local` may safely start a fresh process-local session from versioned policy; timer state is never restored from SQLite.

Viewer can include/search low-attention rows but cannot pin them. Admin pin/unpin affects list visibility only and never mutates source opinions or history.
