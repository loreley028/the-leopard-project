# 板块行情及技术指标口径

板块研究使用高密度表格展示当日与近5日0轴涨跌柱（涨红跌绿，同时保留百分比数字）、MA5/MA20偏离和最近5期路径。详细行展开提供最近20日收盘、MA5、MA20和成交量；指标不足显示“历史不足”，不得以0或推测值代替。

所有指标由后端计算且只使用按交易日升序的 `complete_eod` 数据：

- `MA_N`：包含当前交易日的最近 N 个收盘价简单平均。
- `return_N = close_t / close_(t-N) - 1`，因此至少需要 N+1 条。
- `volume_ratio_N = 当日 volume / 此前 N 个完整交易日的平均 volume`，当前日不进入分母。
- `close_vs_maN_pct = close_t / MA_N - 1`。
- 数据不足返回 `null` 和 `history_insufficient`，不填 0、不估算、不使用未来数据。
- `amount` 可空且不得反推；`turnover_rate` 暂不作为首版必须字段。

数据合同还保留 `eod_status`、`data_source`、`provider_role`、`fetched_at` 和 `source_response_hash`。公共网页端点当前角色固定为 `diagnostic_provider`，文件导入标记为 `research_provider`；两者都不代表生产可靠性，`production_primary` 仍不存在。
## Active holding interval

“本轮持有期涨跌幅” starts at the most recent `turn_hold` market close and continues while the effective status is `turn_hold` or `hold`, including reports marked `not_mentioned`. Explicit watch/weak/exit/avoid statuses close it. Unknown start and missing real market data remain explicit nonnumeric states; the UI never calculates or fabricates the value.

`return_5d` uses the five complete daily returns compounded (equivalent to the appropriate start/end close ratio), never a simple percentage sum. APIs also return `recent_5_trading_days` with date, daily percentage, close and `eod_complete` status. Missing sessions are not filled with zero.

Holding intervals now read the complete frozen path ledger. Formal returns use only EOD start/end closes. A cached intraday value may provide a separately labelled reference return but never replaces the formal result. Path ranges (10/20/40/60 report periods) and chart ranges (20/40/60 trading days) are different contracts.

Strict holding ends on strong-watch; broad holding permits strong-watch and ends only on watch or weaker exit states. Both are computed server-side from the same frozen ledger.
