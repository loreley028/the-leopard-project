# 66 板块 Provider 覆盖报告（最终口径）

机器可读明细：[coverage.json](../data/provider-validation/coverage.json)。主分类互斥，每个业务板块只出现一次。

## 互斥分类

| 主分类 | 实际数量 | 含义 |
|---|---:|---|
| `direct_full` | 60 | 直接取得真实行情且至少120日 |
| `direct_short_history` | 1 | 映射有效但历史不足120日 |
| `cross_market_special` | 1 | HSTECH，需独立港股代码及日历 |
| `custom_composite_ready` | 3 | 固定权重组合基础数据齐全 |
| `proxy_only` | 1 | 酒店餐饮使用显式代理881160 |
| `unavailable` | 0 | 当前没有完全无真实数据的业务板块 |
| **合计** | **66** | 严格等于映射总数 |

## 可重叠统计

| 统计 | 数量 |
|---|---:|
| `has_any_real_data` | 66 |
| `has_120_days` | 65 |
| `has_amount` | 65 |
| `requires_custom_calculation` | 3 |

这些统计可以重叠，不与互斥主分类相加。

## 特殊项目

- 玻璃基板 `886111`：14日真实历史，分类为 `direct_short_history`；保留原映射，不自动替换。
- 恒生科技：内部 `HSTECH/HK`，同花顺 `HS2083`，Tushare `HKTECH`；分类为 `cross_market_special`。
- 酒店餐饮：`881160` 已获准作为首版临时代理，分类为 `proxy_only`，所有输出必须保留 `data_status=proxy`。
- 食品饮料、光伏/储能、石油石化：基础序列齐全，分类为 `custom_composite_ready`。

没有把公共网页端点提升为生产 Provider，也没有修改66板块名称、一级分组或研究映射历史。
