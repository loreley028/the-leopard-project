# Provider 字段契约（Phase 1A 最终版）

业务层只依赖 `MarketDataProvider` 和统一 `DailyBar`，不得直接依赖第三方 SDK。日期升序且唯一，数值使用 `Decimal`，原始响应记录 SHA-256，不用模型或推测值补行情。

## 行情字段

| 字段 | 必填 | 口径 |
|---|---|---|
| open/high/low/close | 是 | 指数点位，必须满足 OHLC 自洽 |
| pre_close/change/pct_change | 是 | 昨收、点位变化、百分数涨跌幅；窗口边界需多取一个前序交易日 |
| volume | 否 | 独立保存；不与其他板块绝对量横向排名 |
| turnover_rate | 否 | 独立保存，不与 volume 或 amount 混用 |
| amount | 否 | 原始成交额；缺失不使行情无效，禁止由其他字段推算 |
| liquidity_status | 是 | `complete`：volume 与 amount 均可用；`partial`：只可用部分流动性字段；`unavailable`：均不可用 |
| data_status | 是 | 包括 `normal`、`proxy`、`history_insufficient`、`stale_snapshot`、`provider_anomaly`、`missing` |

Tushare `ths_daily` 的成交量单位为“手”，且不提供 `amount`；不同 Provider 的 volume 单位必须由各自适配器按合同转换，不能直接假设一致。[官方字段定义](https://tushare.pro/document/2?doc_id=260)

## 指标与历史长度

- 短历史保存全部真实记录；5/10日等满足长度的指标照常计算。
- 不满足长度的20/60/120日指标返回不可用，并以 `history_insufficient` 解释原因；不得用空行、重复行或推测行补齐。
- 要求120日完整历史的排名先按历史长度过滤。玻璃基板 `886111` 当前不进入该排名；达到120日后自动恢复。
- 放量缩量分别计算同一 symbol 的 `volume / MA5(volume)` 与 `volume / MA20(volume)`。
- `amount` 缺失时 amount 类指标为空，但价格、收益和 volume 指标继续有效。

## Provider 标识转换

统一模型保存 `HSTECH + HK`。Provider 边界转换如下：

| Provider | 外部代码 |
|---|---|
| 同花顺公共诊断端点 | `HS2083` |
| Tushare 候选主源 | `HKTECH` |

CN_A 与 HK 使用各自交易日历。A 股休市而港股开市时，保存 HK 行，不制造 A 股占位行。

## 异常和重试

空响应、无效代码、格式错误、超时、限流、名称不一致、`stale_snapshot` 和历史长度异常分别分类。只有超时、限流和部分网络错误可有限重试；Phase 1A 验证默认不自动重试。
