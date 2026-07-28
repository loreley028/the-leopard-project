# 板块历史路径状态

状态颜色采用高识别度实心填充：深灰蓝不碰、黄色强观/观察、米灰弱观、橙色转持、红色持有、浅绿色转弱、深绿色离场、浅灰未提。颜色之外必须同时显示中文状态；`not_mentioned`不表示观点失效。

版本化合同位于 `config/sector_path_status_v1.json`：

| 代码 | 展示 |
|---|---|
| `avoid` | 不碰 |
| `strong_watch` | 强观 |
| `watch` | 观察 |
| `weak_watch` | 弱观 |
| `turn_hold` | 转持 |
| `hold` | 持有 |
| `turn_weak` | 转弱 |
| `exit` | 离场 |
| `not_mentioned` | 未提 |

颜色属于配置，但任何界面必须同时显示文字。未知状态返回 `unknown_path_status` 并进入人工复核。`not_mentioned` 不延续上一期状态，也不表示观点失效；页面可同时显示本期“未提”和最近明确观点。
## Reported and effective status

`reported_status` is the current PDF cell. `effective_status` is the latest explicit status. `not_mentioned` is not a state change, does not cancel a view, and does not close an active holding interval. Comparisons use the last two explicit statuses.
