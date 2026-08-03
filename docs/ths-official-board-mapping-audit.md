# THS 正式板块映射审计

> 状态：research-only。本文不接入 Provider、不修改正式映射、不证明盘中可用性。

## 结论

对正式 registry 的 66 条 active market path 动态审计结果如下：

| 分类 | 数量 |
|---|---:|
| 单一 THS exact 正式板块 | 61 |
| 明确 proxy | 1 |
| 既定指数复合路径 | 3 |
| 代码需要纠正 | 0 |
| 真正语义缺口 | 1 |
| 已有 THS 语义覆盖（包含复合） | 65 |

唯一真实语义缺口是 `catering`。它不能由酒店、旅游、食品、预制菜或零售静默替代。三个既定复合路径仍是食品饮料、光伏储能、油气石化；本审计不批准它们进入生产。

因此，之前把 CPO、商业航天、算力租赁、液冷、玻璃基板、AI 应用、互联网金融、光纤题材、稀土或创新药/医药列入自建篮子候选的推断不成立：这些路径已有项目中留存的精确 THS 正式板块身份。板块不存在、代码错误和网页访问失败是三类不同问题。

## 重点路径

| 路径 | 正式 THS 名称 | 代码 | 结论 |
|---|---|---:|---|
| CPO | 共封装光学(CPO) | 886033 | exact；不进入篮子候选 |
| 商业航天 | 商业航天 | 886078 | exact；不进入篮子候选 |
| 算力租赁 | 算力租赁 | 886050 | exact |
| 液冷 | 液冷服务器 | 886044 | exact |
| 玻璃基板 | 玻璃基板 | 886111 | exact |
| AI 应用 | AI应用 | 886108 | exact |
| 互联网金融 | 互联网金融 | 885456 | exact |
| 光纤题材 | 光纤概念 | 886084 | exact |
| 稀土 | 稀土永磁 | 885343 | exact |
| 创新药/医药 | 创新药 | 886015 | exact |
| 酒店 | 旅游及酒店 | 881160 | 明确 proxy |
| 餐饮 | — | — | 无独立适合板块；唯一未来篮子/暂不可用候选 |

商业航天的公开详情页可见正式标题“商业航天886078”、现价、昨收及成分排行，直接证明该板块存在且不应以泛军工替代。[商业航天公开页面](https://q.10jqka.com.cn/thshy/detail/code/886078/)

## 当前访问问题

当前 `ths_exact_spot` 的每个详情请求都使用同一个 URL 家族：

```text
https://q.10jqka.com.cn/thshy/detail/code/{symbol}/
```

它的 HTML 解析器提取 `current`、`pre_close`、开高低、成交量和成交额；它没有从源页面解析 `as_of`。共享传输层只特别分类 429 和 404，未单独处理的 401 会被归为 generic network。因此：

- 某个详情请求的 401 是 `provider_access_problem`，不是板块不存在；
- 项目现有 62 条单板块路径不应因同一访问端点故障改成篮子；
- 3 条复合路径仍需其既定两项正式成分，不应改为单板块；
- 没有发现需要修改的现有板块代码。

本轮的一次 CPO 无认证结构读取只得到 59 字节、没有可解析字段；该读取未持久化完整响应，且未记录 HTTP 状态，不能推翻 CPO 的正式板块身份，也不能作为 live 成功证据。

## 匿名公共读取路径

| access path | 匿名 GET | current / pre_close | source as_of | 成分 | 历史 | 当前结论 |
|---|---|---|---|---|---|---|
| `ths_detail_html` | 是 | 页面候选可读 | 尚未验证 | 页面候选可读 | 否 | `candidate_for_cloud_probe` |
| `ths_board_daily_chart` | 是 | 否 | 否 | 否 | 是 | `insufficient_fields` |

`ths_board_daily_chart` 是现有 validation-only 日线适配器使用的公开 callback 路径；它只能辅助历史，不能冒充当前交易时段快照。当前没有一条匿名路径被验证为同时稳定提供 `current`、`pre_close` 和源端 `as_of`。

## 审计约束

- 结果由正式 registry 和当前 capability matrix 动态派生，未手写另一份 66 条目录；
- 研究输出与真实网络响应仅写入被忽略的 `var/provider-research/ths-public-board-audit/`；
- 无 Cookie、Token、登录、浏览器自动化、签名破解、User-Agent 轮换或重试；
- 正式 registry、candidate chain、Scheduler、Viewer、EOD、数据库、UI 与部署均未改变。

下一步只应在下一交易日执行五个代表路径的隔离容器探测，验证匿名详情页能否同时提供三项必需字段。
