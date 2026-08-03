# THS 匿名公共板块路径云端探测 Runbook

> 仅用于下一交易日 09:45—10:15 的一次性阿里云隔离容器研究验证。

## 前置条件

- 正式 `current`、SQLite、shared、`production.env` 均不挂载；
- 不启动 API、Scheduler、EOD，不绑定端口，不设置 restart policy；
- spike 源码只读，输出目录独立可写；
- 无 Token、Cookie、登录态或浏览器自动化；
- 当前市场须由服务器交易日历确认处于开市状态。

## 代表探测

运行：

```bash
PYTHONPATH=backend python3.12 scripts/validate_ths_public_board_paths.py \
  --run-live \
  --environment-label aliyun_isolated \
  --timeout 15 \
  --output-dir /tmp/ths-public-board-audit
```

代表路径由审计结果动态取得，而不是硬编码：CPO、商业航天、酒店、半导体、算力租赁。每个 `provider + symbol + access path` 最多一次请求，串行执行，不重试。

每条记录必须包含 HTTP 状态、Content-Type、响应长度、current、pre_close、source as_of、解析状态、耗时和脱敏摘要；不得保存完整响应。

## 分类

| 情况 | 分类 |
|---|---|
| HTTP 401 | `http_401` |
| HTTP 403 / 404 / 429 | 对应 `http_403` / `http_404` / `http_429` |
| 200 但缺 current、pre_close 或 source as_of | `insufficient_fields` |
| 连接/DNS/TLS/超时失败 | `network_error` |
| 200 但 HTML 无法解析 | `parser_error` |
| 三项字段均完整 | `success` |

当且仅当至少 4/5 条代表路径达到 `success`，才把 `full_expansion_permitted` 标记为 true。该脚本不会自动扩展到全量代码；扩展需在下一次受控运行中单独授权。

## 停止条件

以下任一情况立即停止，不换路径、不增加请求、不绕过限制：

- 代表路径成功少于 4/5；
- HTTP 401、403、429 或网络失败表明公共路径不可用；
- 缺少源端 `as_of`；
- 隔离条件不成立；
- 结果字段或统计不自洽；
- 发现敏感信息可能进入输出。

收盘后测试页面结构和元数据可以保留，但绝不能把旧价格当作实时验收。
