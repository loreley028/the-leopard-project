# 盘中Provider研究记录

验证日期：2026-07-28；结论不构成生产批准。

## 东方财富板块spot

- 公开`push2.eastmoney.com/api/qt/clist/get`板块列表，与现有同花顺历史日线端点不同。
- 血缘为东方财富push2；AKShare与efinance相关板块接口共享该上游，并非独立第二源。
- 本次不需要Token、Cookie、账号或积分。东方财富公开页面实测半导体`BK1036`在2026-07-28 13:14:15显示现价2564.28、昨收2675.21、涨跌幅-4.15%、开高低2611.05/2675.09/2543.61、成交量3355万和成交额2704亿。
- 适配器每个五分钟周期只请求行业/概念两个列表，名称仅允许精确或唯一确认别名；不明确和自定义组合会逐板块记录失败，不静默替换。成功快照允许写入忽略的`real_local`缓存，绝不进入EOD、指标或报告快照。
- 分类：`partially_validated`、`research_provider`。2026-07-28 14:01（Asia/Shanghai）的服务器统一刷新实测覆盖8/65：广告营销、AI应用、啤酒、教育、小家电、软件开发、旅游及白色家电；其余57项明确记录为`provider_failed`。14:43复测短暂取得9/65，14:56再次刷新为0/65、65项`provider_failed`，页面按最新run如实显示0/65并保留此前有效快照，不用旧EOD或旧盘中值冒充当前实时数据。波动结果进一步说明当前公开端点只证明局部可达性，不能宣称全覆盖或生产可靠。

参考：[AKShare官方指数接口文档](https://akshare.akfamily.xyz/data/index/index.html)、[东方财富半导体板块页面](https://quote.eastmoney.com/bk/90.BK1036.html)、[efinance官方仓库](https://github.com/Micro-sheep/efinance)及其[限流说明](https://github.com/Micro-sheep/efinance/discussions/216)。

## 新浪行业聚合

- `vip.stock.finance.sina.com.cn/q/view/newSinaHy.php`，血缘为新浪财经行业聚合。
- 无Token或Cookie，HTTP 200；但编码、概念覆盖、映射和权威时间戳不足。
- 分类：`partially_validated`，不能覆盖65个业务口径，禁止写入real_local。

## 2026-07-28阶段决策

当日没有候选达到`live_validated`。系统保留上一有效缓存并对本轮失败显示`provider_failed`，不伪造盘中行情；`production_primary`仍不存在。历史日线与`fetch_intraday_snapshot`已在Provider合同中分离。

## 2026-07-29同源序列修订

- 上一版最新真实轮次在加载全部显式别名后为63/65；算力租赁与零售因不允许模糊替换而失败。
- 更关键的阻塞是东方财富实时`BK`点位不能与项目既有同花顺正式EOD点位拼接。此前生成的跨源实时MA5仅用于发现问题，不能作为验收结果。
- 修订后的链路要求东方财富当前值只配同一`BK`代码的东方财富原生日线；算力租赁固定`886050`、零售固定`881158`、小家电固定`881173`，只走各自同花顺精确页面和同代码日线。
- 原生历史、盘中快照与正式EOD分表保存。Provider、Provider symbol、交易日期或昨收尺度不一致时，实时MA5返回不可用。
- 10:13轮次诚实暴露小家电公共列表名称不再能唯一匹配，结果为64/65；随后依据既有V2.3正式代码`881173`改走精确同花顺页面，没有用近似板块替代。

### 本地真实验收结果

以下三轮均在Asia/Shanghai交易时段由同一五分钟本地循环产生；每轮计划65项、成功65、失败0、fresh 65、stale 0、unsupported 1，且HSTECH请求数为0。每轮62项走`eastmoney_board_spot`、3项走`ths_exact_spot`；每轮65项均保存同Provider、同Provider symbol的前4个完整收盘并计算实时MA5。

| 轮次 | run id | 开始时间 | 结束时间 | 耗时 | 成功 |
|---|---|---|---|---:|---:|
| 1 | `71c775b3894748e09e077674f408eed7` | 2026-07-29 10:17:07 | 10:17:22 | 15.590秒 | 65/65 |
| 2 | `e3385f09567a44ba80a2d4460588a054` | 2026-07-29 10:22:07 | 10:22:08 | 1.076秒 | 65/65 |
| 3 | `84210c9cbb88499c900f5211cc455938` | 2026-07-29 10:27:07 | 10:27:08 | 1.044秒 | 65/65 |

首轮加载并节流请求Provider原生历史；后两轮复用同一进程中按Provider symbol和交易日缓存的已验证历史，只重新取得实时值。该结果只把当前显式研究链标记为Phase 2A-0本地`live_validated`，不构成数据授权、SLA、独立双源或生产批准；所有来源仍是`research_provider`，`production_primary`仍不存在。
