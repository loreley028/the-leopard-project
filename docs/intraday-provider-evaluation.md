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

## 决策

没有候选达到`live_validated`。系统保留上一有效缓存并对本轮失败显示`provider_failed`，不伪造盘中行情；`production_primary`仍不存在。历史日线与`fetch_intraday_snapshot`已在Provider合同中分离。
