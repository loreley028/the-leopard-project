# 报告日期与行情日期合同

- `report_date`：PDF/直播的业务归属日期，由管理员确认；上传时间不能替代。
- `market_as_of_date`：增强报告使用的最近完整 A 股交易日，由系统提出候选、管理员单独确认。
- 周日报告通常绑定受控日历中的最近一个完整交易日，例如 `2026-07-19 → 2026-07-17`，不得绑定周日或下一周一。
- 周一至周四仅在 16:30 后且 EOD 门控为 `complete_eod` 时才可建议当日。
- `intraday_snapshot`、`stale_snapshot`、`future_snapshot`、`provider_failed` 不得进入正式指标或报告快照。
- 日期必须来自版本化 `TradingCalendar`/受控 fixture，或由 `real_local` 中至少60个受支持板块的真实 `complete_eod` 同日记录直接证明；绝不以自然工作日猜测交易日。既不在受控日历中、也没有充分真实覆盖时继续 fail closed。
