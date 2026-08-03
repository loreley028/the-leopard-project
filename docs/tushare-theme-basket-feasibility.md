# Tushare 主题篮子可行性研究

> 状态：离线 research spike；不是 Provider 接入方案，不构成生产批准。
>
> 评估日期：2026-08-03。未读取 Token，未调用 Tushare、阿里云或任何行情 Provider。

## 结论

“申万公开指数 + 3 个透明组合 + 少量主题篮子”目前只能给出**接近门槛、尚未通过**的结论。

| 口径 | 覆盖 |
|---|---:|
| 申万 exact | 45 |
| 已明确可接受 proxy | 7 |
| exact + proxy | 52 |
| 3 个组合全部获用户批准后的理论覆盖 | 55 |
| 已达到 `custom_basket_promising` 的主题篮子 | 0 |
| 当前可计入的 promising 理论覆盖 | 55/66 |
| 仅把 9 个 caveat 候选全部视为未来可行时的研究上限 | 64/66 |

研究上限 64/66 不等于已验证覆盖。由于本轮不得使用 Token 或访问接口，无法取得带日期的成分快照、成分数量、集中度和历史稳定性证据；因此没有任何主题篮子可以被标记为 `custom_basket_promising`。

最终状态：

- `tushare_channel_near_threshold`
- `additional_source_or_business_decision_required`
- `production_primary` 仍未批准

## 可用接口合同的离线证据

以下只证明官方文档存在相应能力，不证明当前账号权限、返回质量、展示授权或阿里云可达性：

- `ths_index` 提供同花顺板块目录；官方文档标明 6000 积分，一次可取全部数据：<https://tushare.pro/document/2?doc_id=259>
- `ths_member` 提供同花顺板块成分；官方文档标明 6000 积分、200 次/分钟，但 `weight`、`in_date`、`out_date` 字段目前标记为暂无：<https://tushare.pro/document/2?doc_id=261>
- `ths_daily` 提供同花顺板块历史日线：<https://tushare.pro/document/2?doc_id=260>
- `dc_index`、`dc_member`、`dc_daily` 分别提供东方财富板块目录、按日期成分和历史日线：<https://tushare.pro/document/2?doc_id=362>、<https://tushare.pro/document/2?doc_id=363>、<https://tushare.pro/document/2?doc_id=382>
- `tdx_index`、`tdx_member`、`tdx_daily` 提供通达信板块目录、成分和日线：<https://tushare.pro/document/2?doc_id=376>、<https://tushare.pro/document/2?doc_id=377>、<https://tushare.pro/document/2?doc_id=378>
- `rt_k` 提供 A 股实时日线快照；它与积分接口分开授权：<https://tushare.pro/document/2?doc_id=372>
- `rt_sw_k` 提供申万指数实时快照；它也是独立授权：<https://tushare.pro/document/2?doc_id=417>

## 三个透明组合

三个组合沿用研究基线里的正式组成和 50/50 权重，不修改业务定义。每个组合都给出两种可审计算法：

1. `equal_weight_index_return`：两个组成指数收益等权合成；
2. `fixed_explicit_business_weight`：使用已存在的 50/50 业务权重。

两种算法当前数值相同，因为没有证据支持其他权重。所有组合仍需用户批准，且不能在没有组成指数实时报价、昨收和同源历史时计算。

| 组合 | 组成 | 权重 | 主要语义风险 |
|---|---|---:|---|
| 食品饮料 | 801124.SI 食品加工 + 801127.SI 饮料乳品 | 50% / 50% | 是项目的窄口径，不代表申万完整食品饮料行业 |
| 光伏储能 | 801735.SI 光伏设备 + 801737.SI 电池 | 50% / 50% | “电池”宽于“储能” |
| 油气石化 | 801963.SI 炼化及贸易 + 801962.SI 油服工程 | 50% / 50% | 油服工程不等同于油气开采及服务，存在实质语义差异 |

在没有成分快照时，无法排除组成指数间重叠，不能宣称没有重复计权。

## 主题路径逐项判断

所有候选名称都带“（自定义篮子）”，以避免误导为官方指数。代码仅用于未来低频、经授权的成分核验；当前没有进入正式 Provider 候选链。

| canonical path | 候选目录代码 | 结论 | 当前阻塞 |
|---|---|---|---|
| `optical_fiber_theme` | 886084.TI / BK1660.DC | `custom_basket_possible_with_caveats` | 成分、集中度和稳定性未认证 |
| `innovative_drug_medicine` | 886015.TI / BK1106.DC | `requires_user_decision` | canonical 同时包含创新药和较宽医药范围，需先决定口径 |
| `cpo` | 886033.TI / BK1128.DC | `custom_basket_possible_with_caveats` | 尚无带日期成分快照；不得以宽泛通信板块替代 |
| `computing_power_rental` | 886050.TI | `custom_basket_possible_with_caveats` | THS 文档中的进出日期字段不可用，点时历史难以重建 |
| `liquid_cooling` | 886044.TI / BK1138.DC | `custom_basket_possible_with_caveats` | 需核查非服务器液冷业务的混入 |
| `glass_substrate` | 886111.TI / BK1175.DC | `custom_basket_possible_with_caveats` | 新主题，成分历史长度和稳定性未知 |
| `ai_applications` | 886108.TI / BK1629.DC | `custom_basket_possible_with_caveats` | 主题较宽，可能混入弱相关软硬件公司 |
| `catering` | 880423.TDX（拒绝） | `unsuitable_for_custom_basket` | 官方示例是“酒店餐饮”，不能拿酒店、旅游或食品股替代独立餐饮 |
| `internet_finance` | 885456.TI / BK0637.DC | `custom_basket_possible_with_caveats` | 跨银行、券商、软件和平台，异质性高 |
| `rare_earth` | 885343.TI / BK0578.DC | `custom_basket_possible_with_caveats` | THS 扩展到永磁下游；需核查稀土业务纯度 |
| `commercial_space` | 886078.TI / BK0963.DC | `custom_basket_possible_with_caveats` | 必须排除没有商业航天暴露的泛军工公司 |

优先进行未来认证核验的五项是 CPO、液冷、玻璃基板、AI 应用、商业航天。优先级只表示研究顺序，不构成采用决定。

## 自定义篮子计算合同

推荐 MVP 使用等权，规则如下：

- 成分来源必须是明确接口、明确概念代码、明确 `membership_as_of` 的快照；
- 仅纳入 A 股普通股；调仓时剔除 ST 和上市未满 20 个完整交易日的股票；
- 每月首个交易日调仓；最少 5 个有效成分；单股权重上限 20%；
- 当前值使用相同成分快照下的成分 `current / pre_close` 收益合成；
- 任何必需实时值或昨收缺失时 fail closed，不补零；
- 停牌只有在认证行情明确给出停牌状态和有效昨收时才允许零收益；
- 历史必须使用点时成分快照，禁止用当前成分回填历史；
- MA5 = 当前篮子点位 + 前 4 个完整篮子收盘，再除以 5；
- lineage 必须包含 canonical path、成分来源、源概念代码、快照日期、成分、权重、报价时间和剔除项。

## 仍需的证据

每个拟提升为 `custom_basket_promising` 的路径至少需要：

1. 经授权 API 返回的带日期成分快照；
2. 成分数量不少于 5；
3. 逐股语义抽查和无关股票风险结论；
4. 集中度和 20% 权重上限验证；
5. 至少若干月的成分变动证据，确认历史可点时重建；
6. 实时 `current`、`pre_close` 与日线历史的同一数据通道验证；
7. 两次受控重复运行的一致性；
8. 展示、缓存、衍生计算和服务器调用获得提供方确认。

## 建议

不要把本轮 64/66 的最大研究情景写成覆盖成功。下一步有两条安全路径：

- 取得 Tushare 书面权限答复后，用 Token 在独立、明确授权的验证轮次中只核验优先五项的成分快照；或
- 保持 Tushare 只覆盖 55 个官方/透明组合路径，并为剩余主题路径评估第二个有明确授权的独立数据源。

在上述证据完成前，不接入正式 Provider，不修改 Scheduler，不写数据库，不启用 `production_primary`。
