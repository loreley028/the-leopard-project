# 真实行情 Provider 验证（Phase 1A 最终口径）

验收口径固化日期：2026-07-22。本轮仅执行低频、单线程、无自动重试的验证，不写正式数据库、不部署、不启动生产调度。

## Provider 角色

| Provider | 固定角色 | 说明 |
|---|---|---|
| Tushare `ths_daily` | `candidate_primary` | 候选主源，不是已批准生产主源 |
| 同花顺公共网页端点 | `diagnostic_provider` | 只用于代码、字段、覆盖和异常诊断 |
| AKShare 相关适配 | `diagnostic_provider` | 与公共网页端点具有相同上游稳定性风险 |

当前没有任何 Provider 被标记为 `production_primary`。正式准入必须同时完成账号权限验证、66代码转换、全量扫描、连续至少5个交易日双源对账、时效性检查及字段/单位合同验证。Tushare 官方 `ths_daily` 提供板块 OHLC、昨收、涨跌幅和成交量，但没有 `amount`；这不再使行情记录无效，因为首版 `amount` 为可选字段。[Tushare 官方文档](https://tushare.pro/document/2?doc_id=260)

## 实际覆盖结果

最终扫描的互斥主分类为：

- `direct_full`：60
- `direct_short_history`：1
- `cross_market_special`：1
- `custom_composite_ready`：3
- `proxy_only`：1
- `unavailable`：0

合计严格为66。可重叠统计：66项存在真实数据、65项达到120个交易日、65项有 `amount`、3项需要自定义组合计算。

## 已固化业务决策

- 酒店餐饮：canonical sector 保持“酒店餐饮”，首版使用 `881160` 临时代理；`mapping_type=proxy`、`data_status=proxy`。不实现 `881161` 成分股等权指数。将来更换口径必须创建新映射版本和生效日期。
- 玻璃基板：继续使用 `886111`。当前只有14个交易日，属于 `direct_short_history`，不是映射失败；保存全部真实数据，短周期指标正常计算，长度不足的指标标 `history_insufficient`，且不参加完整历史排名。
- 成交额：`amount` 可空，禁止由 volume、avg_price 或其他字段推算。流动性状态由实际可用字段标为 `complete/partial/unavailable`。
- 放量缩量：仅比较同一板块自身 volume 与 MA5-volume、MA20-volume；不做不同板块绝对成交量排名。

## 恒生科技

- 内部标准：`canonical_symbol=HSTECH`、`market=HK`。
- 同花顺公共端点映射：`HS2083`。
- Tushare 映射：`HKTECH`。
- Provider 负责转换；HK 日历独立于 A 股日历。
- `amount` 缺失时行情仍有效，`liquidity_status=partial`。
- 若新快照的截止日期早于已保存水位，标记 `stale_snapshot`；截止日期不变但历史长度减少时记录 `history_length_changed` Provider 异常。异常快照不得静默作为正常数据。

实测中相同公共端点曾分别返回2026年72条和133条快照，证明必须保留上述时效性闸门。HSTECH 的指数身份参见[恒生指数公司](https://www.hsi.com.hk/eng/indexes/all-indexes/hstech)，港股日历参见[HKEX](https://www.hkex.com.hk/Services/Trading/Derivatives/Overview/Trading-Calendar-and-Holiday-Schedule?sc_lang=en)。

## 运行方式

```bash
PYTHONPATH=backend python3.12 -m unittest discover -s tests -v
LEOPARD_RUN_LIVE=1 PYTHONPATH=backend python3.12 -m unittest tests.test_provider_live -v
PYTHONPATH=backend python3.12 -m leopard_project.cli providers validate-live --scope all --output-dir data/provider-validation
```

默认测试不联网。公共端点/AKShare 只作诊断源，不构成生产授权或稳定性承诺。[AKShare 官方项目](https://github.com/akfamily/akshare)
