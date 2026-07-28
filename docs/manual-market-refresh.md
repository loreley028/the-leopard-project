# 手工行情刷新

Viewer 页面不会触发网络请求，浏览器不直接访问 Provider。`real_local`启用服务器统一的盘中缓存和EOD缺口补齐，但不启用生产采集或生产调度。

Admin 行情区显示预期完整日、最近成功日、缺失日期、失败Provider和最近重试时间。手工历史刷新仍须显式确认，也可预览再导入CSV/XLSX。服务器在安全配置下只补完整EOD缺口；盘中缓存可由Admin暂停、恢复或立即刷新。Viewer永不触发刷新。

每次运行保存 `MarketRefreshRun` 和逐板块 `MarketRefreshItem`；单个板块失败不终止整批。真实公共端点固定为 `diagnostic_provider`，不得升级为 `candidate_primary`、`production_primary` 或 `production_fallback`。只保存真实 `complete_eod`，同日冲突不覆盖旧值；导入缺少 `amount` 时保留为空，不推算伪造。

行情刷新后由后端计算日涨跌、5/10/20日收益、MA5/MA10/MA20、均线偏离及 volume/MA5、volume/MA20。报告必须由 Admin 明确绑定 `market_as_of_date` 并固化发布快照；后续刷新不会改写已发布快照。

Manual historical refresh/import remains separate from the intraday cache. Intraday is a process-local Admin session, defaults to five minutes, runs one low-concurrency cycle at a time across 65 supported CN-A sectors, and distributes requests through the cycle window. Viewer reads do not increase request count. Lunch, close and non-trading days issue no requests; failures keep the prior cache and return `provider_failed` instead of zero.
